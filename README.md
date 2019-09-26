TransLCD
========

Simple script that displays the list of active torrents from [Transmission](https://transmissionbt.com/) to an LCD screen controlled by [LCDproc](http://lcdproc.omnipotent.net/).

How to Use
----------

Edit `translcd.conf` to configure the connection to both Transmission and LCDproc, then start the script and leave it running.

An alternate configuration file path can be passed as the first argument.

The LCDproc screen is interactive: use the up/down buttons to scroll the list. A menu is available to change sort order and filtering.

Development
-----------

Useful documentation:

- [LCDproc Developer's Guide](http://lcdproc.sourceforge.net/docs/current-dev.html)
- [Transmission RPC Specification](https://github.com/transmission/transmission/blob/master/extras/rpc-spec.txt)

Tested on a [CFA-635](https://www.crystalfontz.com/product/cfa635yykks-rs232-module-20x4-character-display).
