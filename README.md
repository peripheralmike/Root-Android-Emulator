# Root-Android-Emulator
If you find yourself in need ot testing something on a "rooted" android device and can't get a physical device to root then you can always use the Android Emulator through Android Studio.

Rooting is simply the act of allowing the user (you) to execute commands on the device at the highest level of permissions. These are usually locked out of consumer devices but sometimes you need that level of access for devlopment, software testing or simply to experiment with something.

This guide will take you through rooting an Android Emulator so you can have full access to it.

### This readme was written using MacOS, Windows friendly commands to follow...

## If you encounter any strange bugs during this process or any error messages not mentioned - I encourage you to copy the error message into Google as this will usually offer a solution.

## What you need to do first...
- Go to (link) and download Android Studio

## Example
_What if I want to have root access to a Nexus 5X device running Android 7.1_

This is a very specific scenario however it is something that Software Testers and Developers have come across before. Through this example we'll use this repo to solve that example problem.

# Setup

- Open Android Studio
- Create a new Project (the exact details don't matter)
- Navigate to Tools > SDK Manager
- On the next screen you'll see a list of different Android operating systems
- From this List, cluick the tick box labelled "Show Package Detils" in the lower right corner
- Scroll to the Android 7.1 section
- Here you'll find a lot of different types of System Images. For maxiumum compatibility choose "Google APIs Intel x86 Atom_64 System Image"
_it's important to note at this stage that with the Google API versions of system images, you won't be able to access the Play Store so ensure you have a copy of the .apk file you want to install_
- Tick the tickbox next to the "Google APIs Intel x86 Atom_64 System Image"
- Click Apply
_This will install the system image and might take a few minutes_
- Once finished, click Finish then OK to go back to the main Android Studio window
- Click 'Create Device' in the Device Manager section of Android Studio _If this isn't visable, you can find this by choosing the View > Tool Windows > Device Manager option_
- On the Select Hardware window, choose Nexus 5
- Click Next
- On the Select Image window, click the "x86 Images' near the top of the screen, this will give you more images to select from
- From this new list, find and choose Nougat, API Level 25, ABI x86_64 Target Android 7.1.1 (Google APIs)
- Click next 
- Name you Android Virtual Device (AVD) RootAVD for the purposes of this demo
- Click Finish

# Installing SuperUser App and Binary 
## On MacOS Terminal
- Run the command `~/Library/Android/sdk/emulator/emulator -avd RootAVD -writable-system -selinux disabled -qemu`
_This will start your emulator from the command line and make it writeable for the next steps_
- Open a new Terminal window or tab (Do not close the original one)
- Make sure your terminal is in the directory `/Users/<yourusername>/Library/Android/sdk/platform-tools`
- Still on the Terminal and in the `platform-tools` folder, run `./adb root`
- You should see the response `restarting adbd as root`
- In the same Terminal Window, run 
- You should see the response `remount succeeded`
- At this stage, download the files in this repo (usually by clicking the dropdown arrow next to Code near the top of this GitHub page) save the files as a .zip
Extract the .zip to your Desktop, you should end up with a folder called 'SuperSU' on your Desktop
- Back in the Terminal, run the command `./adb install ~/Desktop/SuperSU/common/Superuser.apk`
- You should see a response similar to `Performing Streamed Install - Success`
_this has installed the 'SuperUser' application onto your emulated device_
- In the same Terminal window, run the command `./adb push ~/Desktop/SuperSU/x86/su /system/xbin/su` you should receive a response that includes something similar to `(253796 bytes in 0.107s)` which means it's worked _This command will move a file from the downloaded files to your device that is needed for rooting the device. It's a binary file for the SuperUser app, there are several different versions of this based on the architecture of your system / application but I'll get into those shortly_
- In the same Terminal window - run the command `./adb shell chmod 0755 /system/xbin/su` You won't get a response from this command but that usually means it's worked. No error message means progress in this case. _This changes the inherent permissions of the 'su' file we just moved so we can run it, different chmod numbers do different things so if you need something different, please Google the exact number you need)_
- In the Terminal, run `./adb shell setenforce 0` You probably won't get a response from this command either, don't worry about it. _This will change the enforcement policy so we can install the binary we need_
- From the Terminal, run `./adb shell su --install` Again, no response from the Terminal, totally normal. _This installs the binary we just moved to work with the SuperUser app_
- Finally in this stage, from the Terminal run the command `./adb shell su --daemon&` This command will give you a response, usually a number similar to the format of `[1] 87611`  _This will allow the SuperUser app to run_

# Enabling Root
- On your emulated device, find and open the SuperSU app.
- You should see a message saying that the Binary needs updating
- Click Continue
- On the next window, choose Normal
- You should now see an 'installing' dialog box...
- Eventually, however, you should see an 'installation failed' prompt. This is totally normal.
- Click OK

# (Optional) Confirming Root
At this stage you have rooted your Android Enulator, however I always like to perform the following steps to make sure it's actually happened.

- From your Teminal window, run the command `./adb install ~/Desktop/SuperSU/common/Terminal.apk` _You should see a response similar to `Performing Streamed Install - Success`_
- On your emulated device, open the newly installed "Terminal Emulator" app
- On this terminal emulator, simply type in `su` and then press return.
- The following dialog popup will ask you if SuperSU should grant root access to this application, press Grant
- If your terminal line now resembles `generic_x86_64:/ #` then *congratulations*, the rooting has worked. If it did not work you would reveive an error at this stage similar to `invalid command`

# Different architectures
As mentioned previously; there are several different architecture configurations for different devices (arm, arm64, armv7, x64, x86 and more)  In the files of this project you'll find similar files for those architectures. Simply change the `x86` to your desired architecture in the `./adb push ~/Desktop/SuperSU/x86/su /system/xbin/su` command

# On Windows 10 Command Prompt
- Open Command Prompt (CMD) as an Administrator
- Run the command `C:\Users\<username>\AppData\Android\Sdk\emulator\emulator -avd RootAVD -writable-system -selinux disabled -qemu`
_This will start your emulator from the command line and make it writeable for the next steps_
- Open a new Terminal window or tab (Do not close the original one)
- Make sure your terminal is in the directory `/Users/<yourusername>/Library/Android/sdk/platform-tools`
- Still on the Terminal and in the `platform-tools` folder, run `./adb root`
- You should see the response `restarting adbd as root`
- In the same Terminal Window, run 
- You should see the response `remount succeeded`
- At this stage, download the files in this repo (usually by clicking the dropdown arrow next to Code near the top of this GitHub page) save the files as a .zip
Extract the .zip to your Desktop, you should end up with a folder called 'SuperSU' on your Desktop
- Back in the Terminal, run the command `./adb install ~/Desktop/SuperSU/common/Superuser.apk`
- You should see a response similar to `Performing Streamed Install - Success`
_this has installed the 'SuperUser' application onto your emulated device_
- In the same Terminal window, run the command `./adb push ~/Desktop/SuperSU/x86/su /system/xbin/su` you should receive a response that includes something similar to `(253796 bytes in 0.107s)` which means it's worked _This command will move a file from the downloaded files to your device that is needed for rooting the device. It's a binary file for the SuperUser app, there are several different versions of this based on the architecture of your system / application but I'll get into those shortly_
- In the same Terminal window - run the command `./adb shell chmod 0755 /system/xbin/su` You won't get a response from this command but that usually means it's worked. No error message means progress in this case. _This changes the inherent permissions of the 'su' file we just moved so we can run it, different chmod numbers do different things so if you need something different, please Google the exact number you need)_
- In the Terminal, run `./adb shell setenforce 0` You probably won't get a response from this command either, don't worry about it. _This will change the enforcement policy so we can install the binary we need_
- From the Terminal, run `./adb shell su --install` Again, no response from the Terminal, totally normal. _This installs the binary we just moved to work with the SuperUser app_
- Finally in this stage, from the Terminal run the command `./adb shell su --daemon&` This command will give you a response, usually a number similar to the format of `[1] 87611`  _This will allow the SuperUser app to run_

adb push C:\Users\<username>\Desktop\SuperSU\x86\su /system/xbin/su 
# Very important to remember that there are different direction slashes for different operating systems. Windows uses \ but android devices uses / so when interacting with both systems with commands like this make sure that you're using the right slashes in the right places.


Variables
You can make this a bit easier by using variables in the path. For example on Windows you could have `C:\Users\<username>\AppData\Android\Sdk` saved as the variable SDK_PATH so you would only need to type in `%SDK_PATH%\emulator` for example

To set a variable on Windows run the command "set VARNAME=VARVAULE" so for this example I'd type `set SDK_PATH=C:\Users\<username>\AppData\Android\Sdk`

I could then check this has worked by using the echo command with `echo %SDK_PATH%` which should print out the full file directlry that I saved

To set a veriable on MacOS run the command "export VARNAME=VARVALUE" so in this example I'd type `export SDK_PATH=/users/<username>/Library/Android/sdk`

I could then ensure that's worked by using the echo command with `echo $SDK_PATH` which should print out the full file directory that I saved.



##### Sources: Modified and expanded from a project by 0xFireball