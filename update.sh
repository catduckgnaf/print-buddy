#!/bin/sh
# Moonraker runs this after the update manager replaces the plugin files.
echo "print-buddy updated"
echo "Spool values in mod_data/user.cfg were not changed."
echo "The macro file is print-buddy.cfg (renamed from print_buddy.cfg). If you"
echo "included print_buddy.cfg by hand, point that include at print-buddy.cfg."
