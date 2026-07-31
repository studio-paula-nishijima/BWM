#!/bin/bash

REPORT="rpi_config_report.txt"

echo "=== Raspberry Pi Configuration Report ===" > $REPORT
echo "Generated: $(date)" >> $REPORT
echo "" >> $REPORT

echo "=== OS ===" >> $REPORT
cat /etc/os-release >> $REPORT
echo "" >> $REPORT

echo "=== Kernel ===" >> $REPORT
uname -a >> $REPORT
echo "" >> $REPORT

echo "=== Hardware ===" >> $REPORT
cat /proc/device-tree/model >> $REPORT
echo "" >> $REPORT


echo "=== Python Versions ===" >> $REPORT
python3 --version >> $REPORT
which python3 >> $REPORT
echo "" >> $REPORT


echo "=== System Python Packages ===" >> $REPORT
dpkg -l | grep python3 >> $REPORT
echo "" >> $REPORT


echo "=== Pip Packages (system Python) ===" >> $REPORT
python3 -m pip list >> $REPORT
echo "" >> $REPORT


echo "=== Virtual Environments ===" >> $REPORT

for VENV in $(find ~ -type f -name pip -path "*/bin/pip" 2>/dev/null)
do
    echo "" >> $REPORT
    echo "--- $VENV ---" >> $REPORT
    $VENV list >> $REPORT
done


echo "=== Systemd Services ===" >> $REPORT
systemctl list-unit-files --type=service >> $REPORT


echo "=== I2C Devices ===" >> $REPORT
i2cdetect -y 1 2>/dev/null >> $REPORT


echo "=== USB Devices ===" >> $REPORT
lsusb >> $REPORT


echo "Report saved to $REPORT"