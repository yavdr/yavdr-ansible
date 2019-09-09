#!/bin/bash
#------------------------------------------------------------------------------
# this script allows searching for a repeat of a recording using epgsearch
# add the following lines to your reccmds.conf
#
# Search for repeat : /path_to_this_script/recrep.sh 0
# Search for repeat with subtitle (same episode): /path_to_this_script/recrep.sh 1
#
# Author: Christian Wieninger (cwieninger@gmx.de)
# Version: 1.1 - 2011-01-16
#
# changed for yavdr (steffenbpunkt@gmail.com)
#
# requirements: grep
#------------------------------------------------------------------------------

# adjust the following lines to your config

# your plugins config dir
PLUGINCONFDIR=/var/lib/vdr/plugins/epgsearch

# do not edit below this line

cat << EOM >/tmp/cmd.sh
INFOFILE="$2/info";

TITLE=\$(grep '^T ' \$INFOFILE);
#cut leading 'T '
TITLE=\${TITLE#*\$T };

EPISODE=\$(grep '^S ' \$INFOFILE)
#cut leading 'S '
EPISODE=\${EPISODE#*\$S };

SEARCHTERM=\$TITLE;

if [ "$1" -eq "1" ]; then
SEARCHTERM=\$TITLE~\$EPISODE;
fi

RCFILE=$PLUGINCONFDIR/.epgsearchrc
echo Search=\$SEARCHTERM > \$RCFILE
#search for this term as phrase
echo SearchMode=0 >> \$RCFILE
if [ "$1" -eq "0" ]; then
    echo UseSubtitle=0 >> \$RCFILE;
fi
echo UseDescr=0 >> \$RCFILE
vdr-dbus-send /Remote remote.CallPlugin string:'epgsearch'
EOM

echo ". /tmp/cmd.sh; rm /tmp/cmd.sh" | at now
