#!../../bin/linux-x86_64/kohzuAriesLynx

#- You may have to change kohzuAriesLynx to something else
#- everywhere it appears in this file

< envPaths

cd "${TOP}"

## Register all support components
dbLoadDatabase "dbd/kohzuAriesLynx.dbd"
kohzuAriesLynx_registerRecordDeviceDriver pdbbase

## Verified production controller endpoint. The controller exposes 32 stable
## IOC slots; model selection is applied separately from the reviewed catalog.
epicsEnvSet("KOHZU_CONTROLLER_HOST", "$(KOHZU_CONTROLLER_HOST=10.1.101.51)")
epicsEnvSet("KOHZU_CONTROLLER_PORT", "$(KOHZU_CONTROLLER_PORT=12321)")
epicsEnvSet("KOHZU_PREFIX", "$(KOHZU_PREFIX=KOHZU:)")
drvAsynIPPortConfigure("KOHZU_TCP", "$(KOHZU_CONTROLLER_HOST):$(KOHZU_CONTROLLER_PORT)", 0, 0, 0)
KohzuAriesLynxCreateController("KOHZU", "KOHZU_TCP", 32, 100, 1000)

## Load record instances
#dbLoadRecords("db/kohzuAriesLynx.db","user=changhui1788")
dbLoadTemplate("db/kohzuAriesLynxMotors.substitutions", "PREFIX=$(KOHZU_PREFIX),MOTOR_PORT=KOHZU")
dbLoadRecords("db/kohzuAriesLynxDiagnostics.db", "P=$(KOHZU_PREFIX),PORT=KOHZU")
# Development status PVs are currently needed by Codex. After development,
# replace this with a final template containing only OriginMethod selection
# and readback, leaving Home/Move/PositionStatus records unloaded.
dbLoadTemplate("db/kohzuAriesLynxHomeDiagnostics.substitutions", "PREFIX=$(KOHZU_PREFIX),MOTOR_PORT=KOHZU")
# DEVELOPMENT SAFETY/COMMISSIONING PVS (disabled for basic end-to-end work).
# dbLoadTemplate("db/kohzuAriesLynxCommissioning.substitutions", "PREFIX=KOHZU:")

## DEVELOPMENT-ONLY: protect direct CA writes to the temporary _able lock.
## Comment this out with SDIS/_able and commissioning after development.
# asSetFilename("${TOP}/db/kohzuAriesLynxAccessSecurity.acf")

cd "${TOP}/iocBoot/${IOC}"
iocInit

## Select initial HOME methods only. Model fields for assigned axes are applied
## by tools/stage_config_apply.py; method choice remains the user's decision.
< applyConfiguredHomeMethods.cmd

## Start any sequence programs
#seq sncxxx,"user=changhui1788"
