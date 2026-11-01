TARGET = iphone:clang:9.3:5.0
ARCHS = armv7
PACKAGE_VERSION = 0.1.0
include $(THEOS)/makefiles/common.mk

APPLICATION_NAME = Igpt
Igpt_FILES = main.m
Igpt_FRAMEWORKS = UIKit QuartzCore MediaPlayer
Igpt_INSTALL_PATH = /Applications
Igpt_CFLAGS = -fno-objc-arc -fblocks

include $(THEOS_MAKE_PATH)/application.mk
