#!/bin/bash

_siegebot_install_code() {
    mkdir -p "$install_dir"
    rsync -a --delete --exclude 'venv' --exclude '.env' "$YNH_APP_BASEDIR/sources/" "$install_dir/"
    if [ ! -x "$install_dir/venv/bin/python" ]; then
        python3 -m venv "$install_dir/venv"
    fi
    "$install_dir/venv/bin/pip" install --quiet --upgrade pip
    "$install_dir/venv/bin/pip" install --quiet -r "$install_dir/requirements.txt"
    chown -R "$app:$app" "$install_dir"
    chmod -R o-rwx "$install_dir"
}
