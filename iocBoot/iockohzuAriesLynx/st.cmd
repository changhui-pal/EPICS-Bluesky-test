#!../../bin/linux-x86_64/kohzuAriesLynx

#- You may have to change kohzuAriesLynx to something else
#- everywhere it appears in this file

< envPaths

cd "${TOP}"

## Register all support components
dbLoadDatabase "dbd/kohzuAriesLynx.dbd"
kohzuAriesLynx_registerRecordDeviceDriver pdbbase

## TCP and motor creation are intentionally disabled in this skeleton.
# Verified controller endpoint; keep disabled until the read-only IOC test.
# drvAsynIPPortConfigure("KOHZU_TCP", "10.1.101.51:12321", 0, 0, 0)
# KohzuAriesLynxCreateController("KOHZU", "KOHZU_TCP", 32, 100, 1000)

## Load record instances
#dbLoadRecords("db/kohzuAriesLynx.db","user=changhui1788")
# dbLoadTemplate("db/kohzuAriesLynxMotors.substitutions", "PREFIX=KOHZU:,MOTOR_PORT=KOHZU")
# Development status PVs are currently needed by Codex. After development,
# replace this with a final template containing only OriginMethod selection
# and readback, leaving Home/Move/PositionStatus records unloaded.
# dbLoadTemplate("db/kohzuAriesLynxHomeDiagnostics.substitutions", "PREFIX=KOHZU:,MOTOR_PORT=KOHZU")
# DEVELOPMENT-ONLY commissioning/lock PVs; do not load in final operation.
# dbLoadTemplate("db/kohzuAriesLynxCommissioning.substitutions", "PREFIX=KOHZU:")

## DEVELOPMENT-ONLY: protect direct CA writes to the temporary _able lock.
## Comment this out with SDIS/_able and commissioning after development.
# asSetFilename("${TOP}/db/kohzuAriesLynxAccessSecurity.acf")

cd "${TOP}/iocBoot/${IOC}"
iocInit

## Enable only after the records above are reviewed and loaded.
# < applyConfiguredHomeMethods.cmd

## Start any sequence programs
#seq sncxxx,"user=changhui1788"
