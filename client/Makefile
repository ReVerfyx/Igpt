# The 10.3 SDK still ships armv7 libraries and is usable for a 5.0 deployment
# target; unlike the stripped 9.3 SDK it is linkable by the Linux Theos toolchain.
TARGET = iphone:clang:10.3:5.0
ARCHS = armv7
PACKAGE_VERSION = 0.1.0
include $(THEOS)/makefiles/common.mk

APPLICATION_NAME = Igpt
Igpt_FILES = main.m
Igpt_FRAMEWORKS = UIKit QuartzCore MediaPlayer
Igpt_INSTALL_PATH = /Applications
Igpt_CFLAGS = -fno-objc-arc -fblocks
# Recent Linux Theos SDK mirrors omit objc_msgSend_stret from their .tbd even
# though it is exported by the iOS 5 armv7 Objective-C runtime. Resolve it at
# load time instead of falsely requiring a simulator-only stub at link time.
Igpt_LDFLAGS = -undefined dynamic_lookup

include $(THEOS_MAKE_PATH)/application.mk
