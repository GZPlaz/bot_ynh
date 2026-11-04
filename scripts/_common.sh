#!/bin/bash

# The clone service's venv and model cache live outside install_dir so backups stay small
# (they're several GB and are simply rebuilt on restore). Computed lazily: $app isn't set until helpers load.
_clone_root() {
    echo "/opt/yunohost/${app}-clone"
}

_is_true() {
    [[ "${1:-0}" =~ ^(1|true|True|yes|y)$ ]]
}

_siegebot_install_code() {
    mkdir -p "$install_dir"
    rsync -a --delete --exclude 'venv' --exclude '.env' --exclude 'clone_server' "$YNH_APP_BASEDIR/sources/" "$install_dir/"
    # keep a copy of the clone service code so the config panel can install it later
    mkdir -p "$install_dir/clone_server"
    rsync -a --exclude 'venv' "$YNH_APP_BASEDIR/clone_server/" "$install_dir/clone_server/"
    if [ ! -x "$install_dir/venv/bin/python" ]; then
        python3 -m venv "$install_dir/venv"
    fi
    "$install_dir/venv/bin/pip" install --quiet --upgrade pip
    "$install_dir/venv/bin/pip" install --quiet -r "$install_dir/requirements.txt"
    chown -R "$app:$app" "$install_dir"
    chmod -R o-rwx "$install_dir"
}

# Settings every script needs before rendering .env (ynh_config_add aborts on unset variables)
_siegebot_default_settings() {
    ynh_app_setting_set_default --key=clone_service --value=0
    ynh_app_setting_set_default --key=clone_api_url --value=""
    ynh_app_setting_set_default --key=clone_token --value="$(ynh_string_random --length=32)"
    clone_service=$(ynh_app_setting_get --key=clone_service)
    clone_api_url=$(ynh_app_setting_get --key=clone_api_url)
    clone_token=$(ynh_app_setting_get --key=clone_token)
}

_siegebot_write_env() {
    ynh_config_add --template="env" --destination="$install_dir/.env"
    chmod 600 "$install_dir/.env"
    chown "$app:$app" "$install_dir/.env"
}

# ---------------------------------------------------------------- voice clone plugin
_clone_install() {
    clone_root="$(_clone_root)"
    ynh_print_info "Installing the voice clone service. This downloads a few GB and can take 10+ minutes..."
    local avail_mb
    avail_mb=$(df -Pm "$(dirname "$clone_root")" | awk 'NR==2 {print $4}')
    if [ "${avail_mb:-0}" -lt 6000 ]; then
        ynh_print_warn "Only ${avail_mb} MB free disk; the clone service needs about 6 GB. Continuing anyway."
    fi
    mkdir -p "$clone_root/hf_cache"
    if [ ! -x "$clone_root/venv/bin/python" ]; then
        python3 -m venv "$clone_root/venv"
    fi
    "$clone_root/venv/bin/pip" install --quiet --upgrade pip
    # CPU-only PyTorch wheels (much smaller than the default CUDA build)
    "$clone_root/venv/bin/pip" install --quiet torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cpu
    "$clone_root/venv/bin/pip" install --quiet -r "$install_dir/clone_server/requirements.txt"
    chown -R "$app:$app" "$clone_root"
    chmod -R o-rwx "$clone_root"

    clone_service=1
    clone_api_url="http://127.0.0.1:$port_clone"
    ynh_app_setting_set --key=clone_service --value=1
    ynh_app_setting_set --key=clone_api_url --value="$clone_api_url"
    _siegebot_write_env

    ynh_config_add_systemd --service="${app}-clone" --template="clone.service"
    yunohost service add "${app}-clone" --description="SiegeBot voice clone service"
    ynh_systemctl --service="${app}-clone" --action="restart"
    ynh_print_info "Voice clone service started. The first start downloads the model (~2 GB) in the background."
}

_clone_remove() {
    clone_root="$(_clone_root)"
    if ynh_hide_warnings yunohost service status "${app}-clone" >/dev/null 2>&1; then
        yunohost service remove "${app}-clone"
    fi
    if [ -f "/etc/systemd/system/${app}-clone.service" ]; then
        ynh_systemctl --service="${app}-clone" --action="stop"
        ynh_config_remove_systemd "${app}-clone"
    fi
    ynh_safe_rm "$clone_root"
    clone_service=0
    clone_api_url=""
    ynh_app_setting_set --key=clone_service --value=0
    ynh_app_setting_set --key=clone_api_url --value=""
}
