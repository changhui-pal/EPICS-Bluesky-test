< envPaths

cd "${TOP}"
dbLoadDatabase "dbd/kohzuAriesLynx.dbd"
kohzuAriesLynx_registerRecordDeviceDriver pdbbase

drvAsynIPPortConfigure("KOHZU_TCP", "10.1.101.51:12321", 0, 0, 0)
KohzuAriesLynxCreateController("KOHZU", "KOHZU_TCP", 32, 100, 1000)

# Controller axis 2 is asyn address 1.
dbLoadRecords "db/kohzuAsynMotor.template", "P=KOHZU:,M=m2,DTYP=asynMotor,PORT=KOHZU,ADDR=1,DESC=KOHZU XA05A-R201,EGU=mm,DIR=Pos,VELO=0.1,VBAS=0.025,ACCL=0.5,BDST=0,BVEL=0.025,BACC=0.5,MRES=0.0005,PREC=4,DHLM=7.35,DLLM=-7.35,INIT=,RTRY=0"
dbLoadRecords "db/kohzuAriesLynxDiagnostics.db", "P=KOHZU:,PORT=KOHZU"
dbLoadRecords "db/kohzuAriesLynxHomeDiagnostics.template", "P=KOHZU:,AXIS=2,PORT=KOHZU,ADDR=1"
dbLoadRecords "db/kohzuAriesLynxCommissioning.template", "P=KOHZU:,AXIS=2"

asSetFilename("${TOP}/db/kohzuAriesLynxAccessSecurity.acf")
iocInit

dbpf "KOHZU:m2_able" 1
dbpf "KOHZU:m2.DISP" 0
dbpf "KOHZU:m2.HVEL" 0.1
dbpf "KOHZU:m2:OriginMethod" 4

cd "${TOP}/iocBoot/${IOC}"
