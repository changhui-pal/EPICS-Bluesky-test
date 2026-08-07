< envPaths

cd "${TOP}"
dbLoadDatabase "dbd/kohzuAriesLynx.dbd"
kohzuAriesLynx_registerRecordDeviceDriver pdbbase

drvAsynIPPortConfigure("KOHZU_TCP", "10.1.101.51:12321", 0, 0, 0)
KohzuAriesLynxCreateController("KOHZU", "KOHZU_TCP", 32, 100, 1000)

# Controller axis 3 is asyn address 2.  Its physical limit inputs are known
# faulty, so commissioning uses short observed moves and Method 10 at center.
dbLoadRecords "db/kohzuAsynMotor.template", "P=KOHZU:,M=m3,DTYP=asynMotor,PORT=KOHZU,ADDR=2,DESC=KOHZU ZA05A-W101 Z,EGU=mm,DIR=Neg,VELO=0.2,VBAS=0.025,ACCL=1.0,BDST=0,BVEL=0.025,BACC=1.0,MRES=0.00025,PREC=5,DHLM=3.92,DLLM=-3.92,INIT=,RTRY=0"
dbLoadRecords "db/kohzuAriesLynxDiagnostics.db", "P=KOHZU:,PORT=KOHZU"
dbLoadRecords "db/kohzuAriesLynxHomeDiagnostics.template", "P=KOHZU:,AXIS=3,PORT=KOHZU,ADDR=2"
dbLoadRecords "db/kohzuAriesLynxCommissioning.template", "P=KOHZU:,AXIS=3"

asSetFilename("${TOP}/db/kohzuAriesLynxAccessSecurity.acf")
iocInit

dbpf "KOHZU:m3_able" 1
dbpf "KOHZU:m3:OriginMethod" 10

cd "${TOP}/iocBoot/${IOC}"
