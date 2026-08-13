< ../iocBoot/iockohzuAriesLynx/envPaths

cd "${TOP}"
dbLoadDatabase "dbd/kohzuAriesLynx.dbd"
kohzuAriesLynx_registerRecordDeviceDriver pdbbase

# Dedicated loopback port for the basic stage-configuration integration
# test. This IOC never references the production controller address.
drvAsynIPPortConfigure("APPLY_ARIES_TCP", "127.0.0.1:22322", 0, 0, 0)
KohzuAriesLynxCreateController("APPLY_KOHZU", "APPLY_ARIES_TCP", 32, 100, 1000)

dbLoadTemplate "db/kohzuAriesLynxMotors.substitutions", "PREFIX=MOCK:,MOTOR_PORT=APPLY_KOHZU"
dbLoadRecords "db/kohzuAriesLynxDiagnostics.db", "P=MOCK:,PORT=APPLY_KOHZU"
dbLoadTemplate "db/kohzuAriesLynxHomeDiagnostics.substitutions", "PREFIX=MOCK:,MOTOR_PORT=APPLY_KOHZU"
# Preserved development-only commissioning records are not part of this test.
# dbLoadTemplate "db/kohzuAriesLynxCommissioning.substitutions", "PREFIX=MOCK:"

# External CA clients may read _able but must use guarded commissioning
# requests to change it. The project motor template assigns the ASG statically.
# asSetFilename("${TOP}/db/kohzuAriesLynxAccessSecurity.acf")

iocInit

epicsThreadSleep(120)
exit
