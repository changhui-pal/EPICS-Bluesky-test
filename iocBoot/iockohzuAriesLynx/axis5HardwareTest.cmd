< envPaths

cd "${TOP}"
dbLoadDatabase "dbd/kohzuAriesLynx.dbd"
kohzuAriesLynx_registerRecordDeviceDriver pdbbase

drvAsynIPPortConfigure("KOHZU_TCP", "10.1.101.51:12321", 0, 0, 0)
KohzuAriesLynxCreateController("KOHZU", "KOHZU_TCP", 32, 100, 1000)

# Controller axis 5 is asyn address 4 and is the yaw stage. It uses the
# verified CCW hardware limit as zero with Method 8.
dbLoadRecords "db/kohzuAsynMotor.template", "P=KOHZU:,M=m5,DTYP=asynMotor,PORT=KOHZU,ADDR=4,DESC=KOHZU RA04A-W01 Yaw,EGU=deg,DIR=Pos,VELO=2,VBAS=0.2,ACCL=0.5,BDST=0,BVEL=0.2,BACC=0.5,MRES=0.002,PREC=3,DHLM=352.134,DLLM=5.214,INIT=,RTRY=0"
dbLoadRecords "db/kohzuAriesLynxDiagnostics.db", "P=KOHZU:,PORT=KOHZU"
dbLoadRecords "db/kohzuAriesLynxHomeDiagnostics.template", "P=KOHZU:,AXIS=5,PORT=KOHZU,ADDR=4"
dbLoadRecords "db/kohzuAriesLynxCommissioning.template", "P=KOHZU:,AXIS=5"

asSetFilename("${TOP}/db/kohzuAriesLynxAccessSecurity.acf")
iocInit

dbpf "KOHZU:m5_able" 1
dbpf "KOHZU:m5.HVEL" 2
dbpf "KOHZU:m5:OriginMethod" 8

cd "${TOP}/iocBoot/${IOC}"
