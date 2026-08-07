TOP=../..

include $(TOP)/configure/CONFIG
#----------------------------------------
#  ADD MACRO DEFINITIONS AFTER THIS LINE
#=============================

DBD += KohzuAriesLynxSupport.dbd
LIBRARY_IOC += KohzuAriesLynx
KohzuAriesLynx_SRCS += KohzuAriesLynxController.cpp
KohzuAriesLynx_SRCS += KohzuAriesLynxProtocol.cpp
KohzuAriesLynx_SRCS += KohzuAriesLynxDiagnostics.cpp
KohzuAriesLynx_SRCS += KohzuAriesLynxSpeedTable.cpp
KohzuAriesLynx_SRCS += KohzuAriesLynxMotion.cpp
KohzuAriesLynx_LIBS += motor asyn
KohzuAriesLynx_LIBS += $(EPICS_BASE_IOC_LIBS)

# Host-side parser test; it does not require an IOC or controller.
TESTPROD_HOST += testKohzuAriesLynxProtocol
testKohzuAriesLynxProtocol_SRCS += testKohzuAriesLynxProtocol.cpp
testKohzuAriesLynxProtocol_SRCS += KohzuAriesLynxProtocol.cpp
testKohzuAriesLynxProtocol_SRCS += KohzuAriesLynxDiagnostics.cpp
testKohzuAriesLynxProtocol_SRCS += KohzuAriesLynxSpeedTable.cpp
testKohzuAriesLynxProtocol_SRCS += KohzuAriesLynxMotion.cpp

#=============================
# Build the IOC application

PROD_IOC = kohzuAriesLynx
# kohzuAriesLynx.dbd will be created and installed
DBD += kohzuAriesLynx.dbd

# kohzuAriesLynx.dbd will be made up from these files:
kohzuAriesLynx_DBD += base.dbd
kohzuAriesLynx_DBD += asyn.dbd
kohzuAriesLynx_DBD += drvAsynIPPort.dbd
kohzuAriesLynx_DBD += motorSupport.dbd
kohzuAriesLynx_DBD += KohzuAriesLynxSupport.dbd

# Include dbd files from all support applications:
#kohzuAriesLynx_DBD += xxx.dbd

# Add all the support libraries needed by this IOC
kohzuAriesLynx_LIBS += KohzuAriesLynx
kohzuAriesLynx_LIBS += motor
kohzuAriesLynx_LIBS += asyn

# kohzuAriesLynx_registerRecordDeviceDriver.cpp derives from kohzuAriesLynx.dbd
kohzuAriesLynx_SRCS += kohzuAriesLynx_registerRecordDeviceDriver.cpp

# Build the main IOC entry point on workstation OSs.
kohzuAriesLynx_SRCS_DEFAULT += kohzuAriesLynxMain.cpp
kohzuAriesLynx_SRCS_vxWorks += -nil-

# Add support from base/src/vxWorks if needed
#kohzuAriesLynx_OBJS_vxWorks += $(EPICS_BASE_BIN)/vxComLibrary

# Finally link to the EPICS Base libraries
kohzuAriesLynx_LIBS += $(EPICS_BASE_IOC_LIBS)

#===========================

include $(TOP)/configure/RULES
#----------------------------------------
#  ADD RULES AFTER THIS LINE
