< ../iocBoot/iockohzuAriesLynx/envPaths

cd "${TOP}"
dbLoadDatabase "dbd/kohzuAriesLynx.dbd"
kohzuAriesLynx_registerRecordDeviceDriver pdbbase

# Dedicated read-only fixed-point dry-run simulator endpoint.
drvAsynIPPortConfigure("FIXED_POINT_TCP", "127.0.0.1:22324", 0, 0, 0)
KohzuAriesLynxCreateController("FIXED_POINT", "FIXED_POINT_TCP", 32, 100, 100)

dbLoadRecords "db/kohzuAsynMotor.template", "P=FIXED:,M=m1,DTYP=asynMotor,PORT=FIXED_POINT,ADDR=0,DESC=Mock X,EGU=mm,DIR=Pos,VELO=0.5,VBAS=0.05,ACCL=0.5,BDST=0,BVEL=0.05,BACC=0.5,MRES=0.0005,PREC=4,DHLM=24.5,DLLM=-24.5,INIT=,RTRY=0"
dbLoadRecords "db/kohzuAsynMotor.template", "P=FIXED:,M=m2,DTYP=asynMotor,PORT=FIXED_POINT,ADDR=1,DESC=Mock Y,EGU=mm,DIR=Pos,VELO=0.1,VBAS=0.025,ACCL=0.5,BDST=0,BVEL=0.025,BACC=0.5,MRES=0.0005,PREC=4,DHLM=7.35,DLLM=-7.35,INIT=,RTRY=0"
dbLoadRecords "db/kohzuAsynMotor.template", "P=FIXED:,M=m3,DTYP=asynMotor,PORT=FIXED_POINT,ADDR=2,DESC=Mock Z,EGU=mm,DIR=Neg,VELO=0.2,VBAS=0.025,ACCL=1.0,BDST=0,BVEL=0.025,BACC=1.0,MRES=0.00025,PREC=5,DHLM=3.92,DLLM=-3.92,INIT=,RTRY=0"
dbLoadRecords "db/kohzuAsynMotor.template", "P=FIXED:,M=m4,DTYP=asynMotor,PORT=FIXED_POINT,ADDR=3,DESC=Mock Pitch,EGU=deg,DIR=Pos,VELO=0.1,VBAS=0.025,ACCL=0.5,BDST=0,BVEL=0.025,BACC=0.5,MRES=0.000637,PREC=6,DHLM=3.429608,DLLM=-3.429608,INIT=,RTRY=0"
dbLoadRecords "db/kohzuAsynMotor.template", "P=FIXED:,M=m5,DTYP=asynMotor,PORT=FIXED_POINT,ADDR=4,DESC=Mock Yaw,EGU=deg,DIR=Pos,VELO=2,VBAS=0.2,ACCL=0.5,BDST=0,BVEL=0.2,BACC=0.5,MRES=0.002,PREC=3,DHLM=173.134,DLLM=-173.786,INIT=,RTRY=0"
dbLoadRecords "db/kohzuAriesLynxDiagnostics.db", "P=FIXED:,PORT=FIXED_POINT"

iocInit

dbpf "FIXED:m1_able" 1
dbpf "FIXED:m2_able" 1
dbpf "FIXED:m3_able" 1
dbpf "FIXED:m4_able" 1
dbpf "FIXED:m5_able" 1

cd "${TOP}/tests"

# Keep the non-interactive IOC alive only for the integration runner. The
# runner normally terminates it earlier; this timeout prevents an orphan.
epicsThreadSleep(30)
exit
