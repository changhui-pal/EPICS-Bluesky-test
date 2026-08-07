< ../iocBoot/iockohzuAriesLynx/envPaths

cd "${TOP}"
dbLoadDatabase "dbd/kohzuAriesLynx.dbd"
kohzuAriesLynx_registerRecordDeviceDriver pdbbase

# This port always targets the local read-only simulator, never real hardware.
drvAsynIPPortConfigure("MOCK_ARIES_TCP", "127.0.0.1:22321", 0, 0, 0)
KohzuAriesLynxCreateController("MOCK_KOHZU", "MOCK_ARIES_TCP", 32, 100, 1000)

# Load all potential axes in generic pulse units. They remain disabled until a
# real stage model supplies engineering units, resolution and travel limits.
dbLoadTemplate "db/kohzuAriesLynxMotors.substitutions", "PREFIX=MOCK:,MOTOR_PORT=MOCK_KOHZU"
dbLoadRecords "db/kohzuAriesLynxDiagnostics.db", "P=MOCK:,PORT=MOCK_KOHZU"
dbLoadTemplate "db/kohzuAriesLynxHomeDiagnostics.substitutions", "PREFIX=MOCK:,MOTOR_PORT=MOCK_KOHZU"

iocInit

# dbpf is available only after iocInit.  Disable every placeholder record
# before accepting any interactive or Channel Access client operations.
< tests/disable_mock_motors.cmd
epicsThreadSleep(0.5)

# Apply initial user selections only. Sensor inventory is advisory and does
# not restrict the controller's Method 1..15 choices.
dbpf "MOCK:m1:OriginMethod" 4
dbpf "MOCK:m2:OriginMethod" 4
dbpf "MOCK:m3:OriginMethod" 10
dbpf "MOCK:m4:OriginMethod" 4
dbpf "MOCK:m5:OriginMethod" 10
epicsThreadSleep(0.5)

# Configure only speed table 0. This command cannot start motor motion.
KohzuAriesLynxConfigureSpeedTable0("MOCK_KOHZU", 1, 100, 1000, 4500)

# A PV write stages Method 10 only in the driver. HOME will change SYS.2 from
# the mock's initial Method 4, read it back, and only then transmit ORG.
dbpf "MOCK:m1:OriginMethod" 10

# Enable only the in-memory mock record while exercising STOP, HOME and moves.
dbpf "MOCK:m1_able" 0
dbpf "MOCK:m1.STOP" 1
epicsThreadSleep(0.1)
dbpf "MOCK:m1.HOMF" 1
epicsThreadSleep(0.1)

# Exercise absolute and relative Model 3 moves after Method 10 establishes 0.
dbpf "MOCK:m1.VAL" 1000
epicsThreadSleep(0.2)
dbpf "MOCK:m1.RLV" 50
epicsThreadSleep(0.2)
dbgf "MOCK:m1:MoveStatus"

# Hold forward JOG briefly. Model 3 passes positive velocity to FRP/CW; release
# uses the already-tested normal STP/0 path. No physical hardware is involved.
dbpf "MOCK:m1.JOGF" 1
epicsThreadSleep(0.2)
dbpf "MOCK:m1.JOGF" 0
epicsThreadSleep(0.2)

# In SET mode, changing the dial coordinate calls Model 3 setPosition(). WRP
# changes only the simulator coordinate, and the driver verifies it with RDP.
dbpf "MOCK:m1.SET" 1
dbpf "MOCK:m1.DVAL" 250
epicsThreadSleep(0.2)
dbgf "MOCK:m1:PositionStatus"
dbpf "MOCK:m1.SET" 0
dbpf "MOCK:m1_able" 1

# Axis 2 retains selected Method 4 while the mock reports SYS.2=10. The mock
# acknowledges WSY but deliberately retains 10; readback must block ORG2.
dbpf "MOCK:m2_able" 0
dbpf "MOCK:m2.HOMF" 1
epicsThreadSleep(0.1)
dbpf "MOCK:m2_able" 1

# Explicit recovery requests: REM must be locally blocked because STR reports
# active EMG, while the user-requested RAX is allowed to refresh the axis map.
dbpf "MOCK:Recovery:ReleaseEMG" 1
epicsThreadSleep(0.1)
dbgf "MOCK:Recovery:Status"
dbpf "MOCK:Recovery:RefreshAxes" 1
epicsThreadSleep(0.1)

# The controller report contains the parsed IDN text and RAX axis count.  The
# integration runner checks these values before considering the test successful.
asynReport 1, "MOCK_KOHZU"
dbgf "MOCK:m1.RBV"
dbgf "MOCK:m6.RBV"
dbgf "MOCK:m1.DMOV"
dbgf "MOCK:m1_able"
dbgf "MOCK:Diag:LastErrorCode"
dbgf "MOCK:Diag:LastErrorText"
dbgf "MOCK:Diag:LastErrorCommand"
dbgf "MOCK:Diag:LastErrorRaw"
dbgf "MOCK:Diag:LastWarningCode"
dbgf "MOCK:Diag:LastWarningText"
dbgf "MOCK:Diag:LastWarningCommand"
dbgf "MOCK:Diag:LastWarningRaw"
dbgf "MOCK:Recovery:EmergencyActive"
dbgf "MOCK:Recovery:Status"
dbgf "MOCK:m1:OriginMethod"
dbgf "MOCK:m1:OriginMethodRBV"
dbgf "MOCK:m1:HomeStatus"
dbgf "MOCK:m1:MoveStatus"
dbgf "MOCK:m1:PositionStatus"
dbgf "MOCK:m2:OriginMethodRBV"
dbgf "MOCK:m2:HomeStatus"

# Axis 3 has no usable sensors, but Method selection remains the user's
# responsibility. Method 4 must therefore be accepted by the driver.
dbpf "MOCK:m3:OriginMethod" 4
epicsThreadSleep(0.2)
dbgf "MOCK:m3:OriginMethod"
dbgf "MOCK:m3:OriginMethodSelectedRBV"
dbgf "MOCK:m3:HomeStatus"
exit
