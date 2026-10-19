#!/bin/sh
# ZMod runs this from the plugin directory after ENABLE_PLUGIN name=print-buddy.
# The cfg is picked up by the plugin include path. This script does not write printer config.
echo "print-buddy installed"
echo "Copy the four slot colors and materials into mod_data/user.cfg, then FIRMWARE_RESTART."
echo "Query with PRINT_BUDDY. It reports matches. It does not switch filament."
