< envPaths

cd "${TOP}"
dbLoadDatabase "dbd/kohzuAriesLynx.dbd"
kohzuAriesLynx_registerRecordDeviceDriver pdbbase

drvAsynIPPortConfigure("KOHZU_TCP", "10.1.101.51:12321", 0, 0, 0)
KohzuAriesLynxCreateController("KOHZU", "KOHZU_TCP", 32, 100, 1000)

# Controller axis 4 is asyn address 3 and is the pitch stage.
dbLoadRecords "db/kohzuAsynMotor.template", "P=KOHZU:,M=m4,DTYP=asynMotor,PORT=KOHZU,ADDR=3,DESC=KOHZU SA05A-R2B01 Pitch,EGU=deg,DIR=Pos,VELO=0.1,VBAS=0.025,ACCL=0.5,BDST=0,BVEL=0.025,BACC=0.5,MRES=0.000637,PREC=6,DHLM=3.429608,DLLM=-3.429608,INIT=,RTRY=0"
dbLoadRecords "db/kohzuAriesLynxDiagnostics.db", "P=KOHZU:,PORT=KOHZU"
dbLoadRecords "db/kohzuAriesLynxHomeDiagnostics.template", "P=KOHZU:,AXIS=4,PORT=KOHZU,ADDR=3"
dbLoadRecords "db/kohzuAriesLynxCommissioning.template", "P=KOHZU:,AXIS=4"

asSetFilename("${TOP}/db/kohzuAriesLynxAccessSecurity.acf")
iocInit

dbpf "KOHZU:m4_able" 1
dbpf "KOHZU:m4.HVEL" 0.1
dbpf "KOHZU:m4:OriginMethod" 4

cd "${TOP}/iocBoot/${IOC}"
