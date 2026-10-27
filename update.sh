#!/bin/sh
# Moonraker runs this after the update manager replaces the plugin files.
echo "print-handy updated"
echo "Spool values in mod_data/user.cfg were not changed."
echo "The macro file is print-handy.cfg (renamed from print_handy.cfg). If you"
echo "included print_handy.cfg by hand, point that include at print-handy.cfg."
