#!/usr/bin/env bash
set -xeE

# should we delete the env and recreate?
source /var/www/wcivf/env/bin/activate
pip install -r /var/www/wcivf/code/requirements.txt
