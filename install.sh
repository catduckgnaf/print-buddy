#!/bin/sh
# ZMod runs this from the plugin directory after ENABLE_PLUGIN name=print-handy.
# ZMod itself adds [include plugins/print-handy/print-handy.cfg] to
# mod_data/plugins.cfg; the cfg file must keep the plugin's name or ZMod
# refuses to enable the plugin. This script does not write printer config.
echo "print-handy installed"
echo "Copy the four slot colors and materials into mod_data/user.cfg, then FIRMWARE_RESTART."
echo "Query with PRINT_HANDY. It reports matches. It does not switch filament."
