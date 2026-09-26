#!/bin/sh
# Runs once IRIS has started, on EVERY container start (docker-compose.yml
# passes it to /iris-main as its --after command).
#
# 1. Un-expire the predefined accounts' passwords (IRIS marks them expired
#    on first start; that state is not in the persisted USER database).
# 2. Install/refresh the IRIS Command Center IPM package from the read-only
#    mounted module.xml + frontend/, so IRIS serves the console at
#    http://localhost:52773/iris-command-center/index.html. Loading again on
#    every start is safe: it refreshes the installed files.
#
# A failure is logged but never stops IRIS.

iris session IRIS -U %SYS '##class(Security.Users).UnExpireUserPasswords("*")' \
  || echo "WARNING: could not un-expire the predefined account passwords"

iris session IRIS -U USER '##class(%IPM.Main).Shell("load /home/irisowner/dev/ -v",1)' \
  || echo "WARNING: could not install the iris-command-center package; the console at /iris-command-center/ may be unavailable"

exit 0
