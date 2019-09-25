#!/usr/bin/env python3.7
import os
import sys
import time
import json
import json.decoder
import array
import base64
import fcntl
import select
import socket
import termios
import urllib.request
import urllib.error
import configparser

if __name__ != '__main__':
	exit()

if len(sys.argv) >= 2:
	cfg_path = os.path.abspath(sys.argv[1])
else:
	cfg_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'translcd.conf')

cfg = configparser.ConfigParser()
cfg.read(cfg_path)

lcdd_socket = socket.socket()
lcdd_socket.connect((cfg['lcdd']['host'], int(cfg['lcdd']['port'])))

line_buffer = b''
line_charset = 'latin-1'

def read_line(until=None):
	global line_buffer
	while True:
		index = line_buffer.find(b'\n')

		if index != -1:
			result = line_buffer[0:index]
			line_buffer = line_buffer[index+1:]
			return result.decode(line_charset, errors='replace')

		if until is None:
			timeout = None
		else:
			timeout = max(0.0, until - time.monotonic())

		rlist, wlist, xlist = select.select([lcdd_socket], [], [], timeout)
		if not lcdd_socket in rlist:
			return

		count = array.array('i', [0])
		fcntl.ioctl(lcdd_socket, termios.FIONREAD, count)
		data = lcdd_socket.recv(count[0])
		line_buffer += data

def write_line(text):
	lcdd_socket.send(text.encode(line_charset, errors='replace') + b'\n')

write_line('hello')
response = read_line()

version = None
protocol = None
width = None
height = None
cell_width = None
cell_height = None

token_state = 0
for token in response.split(' '):
	if token_state == 0:
		token_state = 1 if token == 'connect' else -1
	elif token_state == 1:
		token_state = 2 if token == 'LCDproc' else 3 if token == 'protocol' else 4 if token == 'lcd' else -1
	elif token_state == 2:
		version = token
		token_state = 1
	elif token_state == 3:
		protocol = token
		token_state = 1
	elif token_state == 4:
		token_state = 5 if token == 'wid' else 6 if token == 'hgt' else 7 if token == 'cellwid' else 8 if token == 'cellhgt' else 9
	elif token_state == 5:
		width = int(token)
		token_state = 4
	elif token_state == 6:
		height = int(token)
		token_state = 4
	elif token_state == 7:
		cell_width = int(token)
		token_state = 4
	elif token_state == 8:
		cell_height = int(token)
		token_state = 4
	else:
		break

if token_state == -1:
	raise Exception('Failed to parse handshake response string.')
del token_state

if protocol != '0.3':
	raise Exception('Unsupported LCDd protocol version.')

print(f'Connected to LCDProc {version}, display size {width}x{height}.')

write_line('client_set -name Transmission')
read_line()
write_line('screen_add torrent')
read_line()
write_line('widget_add torrent title title')
read_line()
write_line('widget_set torrent title TRANSMISSION')
read_line()

torrent_count = height - 1

for i in range(0, torrent_count):
	write_line(f'widget_add torrent i{i} icon')
	read_line()
	write_line(f'widget_add torrent t{i} scroller')
	read_line()
	write_line(f'widget_add torrent s{i} string')
	read_line()

screen_active = False
update_interval = int(cfg['update']['interval']) * 0.001
next_update = 0.0

transmission_url = cfg['transmission']['url']
transmission_auth = 'Basic {0}'.format(base64.b64encode('{0}:{1}'.format(cfg['transmission']['username'], cfg['transmission']['password']).encode('utf-8')).decode('utf-8'))
transmission_csrf_token = None
def transmission_query(input):
	global transmission_csrf_token
	while True:
		try:
			request = urllib.request.Request(transmission_url, json.dumps(input).encode('utf-8'), { 'User-Agent': 'TransLCD/0.1', 'Content-Type': 'application/json' })

			if transmission_auth is not None:
				request.add_header('Authorization', transmission_auth)

			if transmission_csrf_token is not None:
				request.add_header('X-Transmission-Session-Id', transmission_csrf_token)

			response = urllib.request.urlopen(request)
			try:
				return json.loads(response.read().decode('utf-8'))
			except json.decoder.JSONDecodeError:
				print(f'{transmission_url}: JSON decode error.', file=sys.stderr)
				return
			finally:
				response.close()
		except urllib.error.ContentTooShortError:
			print(f'{transmission_url}: Content too short.', file=sys.stderr)
			return
		except urllib.error.HTTPError as e:
			if e.code == 409 and 'X-Transmission-Session-Id' in e.headers:
				transmission_csrf_token = e.headers['X-Transmission-Session-Id']
				continue

			print(f'{transmission_url}: HTTP error {e.code}: {e.reason}.', file=sys.stderr)
			return
		except urllib.error.URLError as e:
			print(f'{transmission_url}: URL error: {e.errno}: {e.strerror}', file=sys.stderr)
			return

while True:
	response = read_line(next_update if screen_active else None)
	if response == 'listen torrent':
		screen_active = True
	elif response == 'ignore torrent':
		screen_active = False
	elif response is not None:
		continue

	if not screen_active:
		continue

	query = {
		'method': 'torrent-get',
		'arguments': {
			'fields': [ 'name', 'rateDownload', 'rateUpload' ]
		}
	}

	response = transmission_query(query)

	view_list = []
	try:
		if response['result'] == 'success':
			for torrent in response['arguments']['torrents']:
				torrent_name = torrent['name']
				torrent_dl = torrent['rateDownload']
				torrent_ul = torrent['rateUpload']

				if not torrent_dl and not torrent_ul:
					continue

				torrent_icon = 'ARROW_UP' if torrent_ul > torrent_dl else 'ARROW_DOWN'
				torrent_speed = torrent_dl + torrent_ul
				torrent_unit = 'B'

				if torrent_speed > 999999999:
					torrent_speed /= 1073741824.0
					torrent_unit = 'G'
				elif torrent_speed > 999999:
					torrent_speed /= 1048576.0
					torrent_unit = 'M'
				elif torrent_speed > 999:
					torrent_speed /= 1024.0
					torrent_unit = 'K'

				torrent_speed = str(torrent_speed)[:3]
				if torrent_speed[-1] == '.':
					torrent_speed = torrent_speed[:-1]
				torrent_speed = torrent_speed.rjust(3, ' ') + torrent_unit

				view_list.append((torrent_dl + torrent_ul, torrent_icon, torrent_name.replace('"', '\"'), torrent_speed))
	except KeyError:
		pass

	view_list.sort(key=lambda x: -x[0])

	while len(view_list) < torrent_count:
		view_list.append((0, 'CHECKBOX_OFF', 'N/A', '---B'))

	for i in range(0, torrent_count):
		view = view_list[i]
		write_line(f'widget_set torrent i{i} 1 {i+2} {view[1]}')
		read_line()
		write_line(f'widget_set torrent t{i} 2 {i+2} {width-5} {i+2} h 4 "{view[2]}"')
		read_line()
		write_line(f'widget_set torrent s{i} {width-3} {i+2} "{view[3]}"')
		read_line()

	next_update = time.monotonic() + update_interval
