#!/bin/bash
~/Library/Android/sdk/emulator/emulator -avd RootAVD -writable-system -selinux disabled -qemu &&
./adb root &&
./adb remount &&
./adb install ~/Downloads/SuperSU/common/Superuser.apk &&
./adb push ~/Downloads/SuperSU/x86/su /system/xbin/su &&
./adb shell chmod 0755 /system/xbin/su &&
./adb shell setenforce 0 &&
./adb shell su --install &&
./adb shell su --daemon&




