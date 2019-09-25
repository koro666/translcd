#!/usr/bin/env python3.7
import os
import sys
import time
import array
import fcntl
import select
import socket
import termios
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
write_line('screen_add torrent')
write_line('widget_add torrent title title')
write_line('widget_set torrent title TRANSMISSION')

torrent_count = height - 1

for i in range(0, torrent_count):
	write_line(f'widget_add torrent i{i} icon')
	write_line(f'widget_add torrent t{i} scroller')
	write_line(f'widget_add torrent s{i} string')

screen_active = False
update_interval = int(cfg['update']['interval']) * 0.001
next_update = 0.0

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

	# TODO:
	for i in range(0, torrent_count):
		write_line(f'widget_set torrent i{i} 1 {i+2} CHECKBOX_OFF')
		write_line(f'widget_set torrent t{i} 2 {i+2} {width-5} {i+2} h 1 abcd\u00e9fghijklmnopqrstuvwxyz')
		write_line(f'widget_set torrent s{i} {width-3} {i+2} ---B')

	next_update = time.monotonic() + update_interval
