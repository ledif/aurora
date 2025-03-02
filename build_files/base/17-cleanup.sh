#!/usr/bin/bash

echo "::group:: ===$(basename "$0")==="

set -eoux pipefail

# Hide Desktop Files. Hidden removes mime associations
sed -i 's@\[Desktop Entry\]@\[Desktop Entry\]\nHidden=true@g' /usr/share/applications/fish.desktop
sed -i 's@\[Desktop Entry\]@\[Desktop Entry\]\nHidden=true@g' /usr/share/applications/htop.desktop
sed -i 's@\[Desktop Entry\]@\[Desktop Entry\]\nHidden=true@g' /usr/share/applications/nvtop.desktop

# Disable all COPRs and RPM Fusion Repos and terra
sed -i 's@enabled=1@enabled=0@g' /etc/yum.repos.d/negativo17-fedora-multimedia.repo
sed -i 's@enabled=1@enabled=0@g' /etc/yum.repos.d/tailscale.repo
sed -i 's@enabled=1@enabled=0@g' /etc/yum.repos.d/charm.repo

# Disable terra repos with dnf
dnf5 -y config-manager setopt "terra".enabled=false
dnf5 -y config-manager setopt "terra-mesa".enabled=false
dnf5 -y config-manager setopt "terra-extras".enabled=false
dnf5 -y config-manager setopt "terra-nvidia".enabled=false

# Disable coprs
dnf5 -y copr disable ublue-os/staging
dnf5 -y copr disable ublue-os/packages
dnf5 -y copr disable phracek/PyCharm
dnf5 -y copr disable bieszczaders/kernel-cachyos-addons
dnf5 -y copr disable tulilirockz/fw-fanctrl

# NOTE: we won't use dnf5 copr plugin for ublue-os/akmods until our upstream provides the COPR standard naming
sed -i 's@enabled=1@enabled=0@g' /etc/yum.repos.d/_copr_ublue-os-akmods.repo
sed -i 's@enabled=1@enabled=0@g' /etc/yum.repos.d/fedora-cisco-openh264.repo
sed -i 's@enabled=1@enabled=0@g' /etc/yum.repos.d/hardware:razer.repo
for i in /etc/yum.repos.d/rpmfusion-*; do
    sed -i 's@enabled=1@enabled=0@g' "$i"
done

if [ -f /etc/yum.repos.d/fedora-coreos-pool.repo ]; then
    sed -i 's@enabled=1@enabled=0@g' /etc/yum.repos.d/fedora-coreos-pool.repo
fi

echo "::endgroup::"
