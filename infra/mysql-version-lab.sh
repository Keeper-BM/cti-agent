#!/usr/bin/env bash
# Run as root ONLY inside a disposable Ubuntu 24.04 VM. SSH collector never runs this.
set -euo pipefail
umask 077
action=${1:-}
version=${2:-}
[[ $EUID == 0 && $action =~ ^(baseline|upgrade)$ && $version =~ ^8\.0\.[0-9]+-[a-zA-Z0-9.+~]+$ ]] || {
  echo 'Usage: sudo bash mysql-version-lab.sh baseline|upgrade EXACT_VERSION' >&2; exit 2;
}
source /etc/os-release
[[ $ID == ubuntu && $VERSION_ID == 24.04 ]] || exit 2
evidence=/var/lib/cti-mysql-lab
if [[ $action == baseline ]]; then
  [[ ! -e $evidence && ! -d /var/lib/mysql/mysql && ! -e /usr/sbin/policy-rc.d ]] || {
    echo 'Baseline requires a fresh disposable VM without MySQL or policy-rc.d' >&2; exit 2;
  }
  # Freeze this disposable lab's package state between deliberate administrator steps.
  systemctl disable --now apt-daily.timer apt-daily-upgrade.timer
else
  [[ -f $evidence/baseline.complete && ! -e $evidence/upgrade.complete ]] || exit 2
  old=$(dpkg-query -W -f='${Version}' mysql-server-8.0)
  dpkg --compare-versions "$version" gt "$old" || { echo 'Only forward upgrades are allowed' >&2; exit 2; }
fi
mkdir -p "$evidence/$action/packages"
packages=(mysql-server mysql-server-8.0 mysql-server-core-8.0 mysql-client-8.0 mysql-client-core-8.0)
requested=()
for package in "${packages[@]}"; do requested+=("$package=$version"); done
apt-get update
apt-cache policy "${packages[@]}" > "$evidence/$action/apt-policy.txt"
cp /etc/os-release "$evidence/$action/os-release"
dpkg --print-architecture > "$evidence/$action/architecture.txt"
cp -a /etc/apt/sources.list.d "$evidence/$action/apt-sources"
# Keep the actual signed-repository package downloads and their hashes for reproduction.
(cd "$evidence/$action/packages" && apt-get download "${requested[@]}")
(cd "$evidence/$action/packages" && sha256sum ./*.deb > SHA256SUMS)
find /var/lib/apt/lists -maxdepth 1 -name '*InRelease' -exec cp '{}' "$evidence/$action/" \;
if [[ $action == baseline ]]; then
  printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d
  chmod 755 /usr/sbin/policy-rc.d
  trap 'rm -f /usr/sbin/policy-rc.d' EXIT
fi
DEBIAN_FRONTEND=noninteractive apt-get install -y "${requested[@]}"
if [[ $action == baseline ]]; then
  printf '[mysqld]\nbind-address=127.0.0.1\nmysqlx-bind-address=127.0.0.1\n' > /etc/mysql/mysql.conf.d/zz-cti-lab.cnf
  rm /usr/sbin/policy-rc.d
  trap - EXIT
  systemctl enable --now mysql
  mysql <<'SQL'
CREATE DATABASE cti_lab;
CREATE TABLE cti_lab.restore_probe (id INT PRIMARY KEY, payload VARCHAR(100) NOT NULL);
INSERT INTO cti_lab.restore_probe VALUES (1, 'mysql-version-pair-restore-sentinel');
SQL
fi
systemctl is-active --quiet mysql
mysql --batch --skip-column-names -e 'SELECT id,payload FROM cti_lab.restore_probe ORDER BY id' > "$evidence/$action/sentinel.tsv"
mysql --batch --skip-column-names -e 'SELECT VERSION()' > "$evidence/$action/server-version.txt"
dpkg-query -W -f='${binary:Package}\t${Version}\t${Architecture}\n' "${packages[@]}" > "$evidence/$action/packages.tsv"
ss -ltnp > "$evidence/$action/listeners.txt"
if [[ $action == upgrade ]]; then cmp "$evidence/baseline/sentinel.tsv" "$evidence/upgrade/sentinel.tsv"; fi
touch "$evidence/$action.complete"
echo "PASS: $action $version; package evidence and sentinel saved to $evidence/$action"
