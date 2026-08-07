< envPaths

cd "${TOP}"
dbLoadDatabase "dbd/kohzuAriesLynx.dbd"
kohzuAriesLynx_registerRecordDeviceDriver pdbbase

# Live controller checkout restricted to the physically connected stage on
# controller axis 1.  The driver may discover/poll the other controller axes,
# but no motor records are exposed for them in this IOC.
drvAsynIPPortConfigure("KOHZU_TCP", "10.1.101.51:12321", 0, 0, 0)
KohzuAriesLynxCreateController("KOHZU", "KOHZU_TCP", 32, 100, 1000)

dbLoadRecords "db/kohzuAsynMotor.template", "P=KOHZU:,M=m1,DTYP=asynMotor,PORT=KOHZU,ADDR=0,DESC=KOHZU XA05A-L202,EGU=mm,DIR=Pos,VELO=0.5,VBAS=0.05,ACCL=0.5,BDST=0,BVEL=0.05,BACC=0.5,MRES=0.0005,PREC=4,DHLM=24.5,DLLM=-24.5,INIT=,RTRY=0"
dbLoadRecords "db/kohzuAriesLynxDiagnostics.db", "P=KOHZU:,PORT=KOHZU"
dbLoadRecords "db/kohzuAriesLynxHomeDiagnostics.template", "P=KOHZU:,AXIS=1,PORT=KOHZU,ADDR=0"
dbLoadRecords "db/kohzuAriesLynxCommissioning.template", "P=KOHZU:,AXIS=1"

asSetFilename("${TOP}/db/kohzuAriesLynxAccessSecurity.acf")

iocInit

# Do not accept a motion request until configuration and the explicit guarded
# enable step have completed.
dbpf "KOHZU:m1_able" 1
dbpf "KOHZU:m1.DISP" 0
dbpf "KOHZU:m1:OriginMethod" 4

cd "${TOP}/iocBoot/${IOC}"
