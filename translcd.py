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
	elif token_state == 9:
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
write_line('screen_add torrent')
write_line('widget_add torrent title title')
write_line('client_add_key -shared Up')
write_line('client_add_key -shared Down')

view_height = height - 1

for i in range(0, view_height):
	write_line(f'widget_add torrent i{i} icon')
	write_line(f'widget_add torrent t{i} scroller')
	write_line(f'widget_add torrent s{i} string')

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


def format_icon(dl_speed, ul_speed):
	if dl_speed + ul_speed <= 0:
		return 'CHECKBOX_OFF'
	elif ul_speed > dl_speed:
		return 'ARROW_UP'
	else:
		return 'ARROW_DOWN'


def format_speed(dl_speed, ul_speed):
	result = dl_speed + ul_speed
	unit = 'B'

	if result <= 0:
		return unit.rjust(4, '-')

	if result >= 1000 ** 3:
		result /= 1024.0 ** 3.0
		unit = 'G'
	elif result >= 1000 ** 2:
		result /= 1024.0 ** 2.0
		unit = 'M'
	elif result >= 1000:
		result /= 1024.0
		unit = 'K'

	result = str(result)[:3]
	if result[-1] == '.':
		result = result[:-1]
	result = result.rjust(3, ' ') + unit

	return result


update_interval = int(cfg['display']['interval']) * 0.001
filter_inactive = bool(int(cfg['display']['filter']))
sort_by_speed = bool(int(cfg['display']['sort']))


def make_torrent_view(torrent):
	if not isinstance(torrent, dict):
		return

	name = torrent.get('name')
	if not isinstance(name, str):
		name = ''

	dl_speed = torrent.get('rateDownload')
	if not isinstance(dl_speed, int):
		dl_speed = 0

	ul_speed = torrent.get('rateUpload')
	if not isinstance(ul_speed, int):
		ul_speed = 0

	total_speed = dl_speed + ul_speed
	if filter_inactive and total_speed <= 0:
		return

	return (
		total_speed,
		format_icon(dl_speed, ul_speed),
		name,
		format_speed(dl_speed, ul_speed))


def name_sort_key(view):
	return view[2].lower()


def speed_sort_key(view):
	return (-view[0], view[2])


screen_active = False
next_update = 0.0

view_list = []
empty_view = (0, format_icon(0, 0), '', format_speed(0, 0))
scroll_offset = 0

while True:
	response = read_line(next_update if screen_active else None)
	if response == 'listen torrent':
		screen_active = True
		scroll_offset = 0
		response = None
	elif response == 'ignore torrent':
		screen_active = False
	elif response == 'key Up':
		scroll_offset = max(0, scroll_offset - 1)
	elif response == 'key Down':
		scroll_offset = max(0, min(scroll_offset + 1, len(view_list) - 1))
	elif response is not None:
		continue

	if not screen_active:
		continue

	if response is None:
		query = {
			'method': 'torrent-get',
			'arguments': {
				'fields': [ 'name', 'rateDownload', 'rateUpload' ]
			}
		}

		response = transmission_query(query)

		view_list = []
		if isinstance(response, dict) and response.get('result') == 'success':
			response_arguments = response.get('arguments')
			if isinstance(response_arguments, dict):
				response_arguments_torrents = response_arguments.get('torrents')
				if isinstance(response_arguments_torrents, list):
					for torrent in response_arguments_torrents:
						view = make_torrent_view(torrent)
						if view is not None:
							view_list.append(view)
					del torrent, view
				del response_arguments_torrents
			del response_arguments

			view_list.sort(key=speed_sort_key if sort_by_speed else name_sort_key)
			scroll_offset = max(0, min(scroll_offset, len(view_list) - 1))

	del response

	if scroll_offset <= 0:
		write_line('widget_set torrent title TRANSMISSION')
	else:
		write_line(f'widget_set torrent title "TORRENT {scroll_offset+1}/{len(view_list)}"')

	for i in range(0, view_height):
		j = i + scroll_offset
		view = view_list[j] if j < len(view_list) else empty_view
		write_line(f'widget_set torrent i{i} 1 {i+2} {view[1]}')
		write_line(f'widget_set torrent t{i} 2 {i+2} {width-5} {i+2} h 4 "{view[2]}"')
		write_line(f'widget_set torrent s{i} {width-3} {i+2} "{view[3]}"')

	del j, view

	next_update = time.monotonic() + update_interval
