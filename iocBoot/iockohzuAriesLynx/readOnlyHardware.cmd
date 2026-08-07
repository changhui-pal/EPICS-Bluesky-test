< envPaths

cd "${TOP}"
dbLoadDatabase "dbd/kohzuAriesLynx.dbd"
kohzuAriesLynx_registerRecordDeviceDriver pdbbase

# Actual controller read-only checkout.  No motor, diagnostics, commissioning
# or recovery records are loaded, so this IOC has no operator write PV path.
drvAsynIPPortConfigure("READONLY_ARIES_TCP", "10.1.101.51:12321", 0, 0, 0)
KohzuAriesLynxCreateController("READONLY_KOHZU", "READONLY_ARIES_TCP", 32, 100, 1000)

iocInit

# Allow two idle-poll periods, print the driver snapshots, then exit.  Driver
# construction/polling sends only IDN, RAX, RDP, STR and ROG in this file.
epicsThreadSleep(2.2)
asynReport 1, "READONLY_KOHZU"
exit
