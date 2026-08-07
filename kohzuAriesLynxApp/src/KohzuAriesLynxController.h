#ifndef KOHZU_ARIES_LYNX_CONTROLLER_H
#define KOHZU_ARIES_LYNX_CONTROLLER_H

#include <string>
#include <vector>

#include "asynMotorAxis.h"
#include "asynMotorController.h"
#include "KohzuAriesLynxProtocol.h"

class KohzuAriesLynxController;

// Snapshot assembled from the three read-only per-axis queries RDP, STR and
// ROG. Values remain in controller pulse coordinates at this layer.
struct KohzuAxisSnapshot {
    double position = 0.0;
    bool moving = false;
    bool emergencyStop = false;
    bool originSensor = false;
    bool cwLimit = false;
    bool ccwLimit = false;
    bool homed = false;
};

class KohzuAriesLynxAxis : public asynMotorAxis {
public:
    KohzuAriesLynxAxis(KohzuAriesLynxController* controller, int axisNo);

    void report(FILE* fp, int details) override;

    asynStatus move(double position, int relative, double minVelocity,
                    double maxVelocity, double acceleration) override;
    asynStatus moveVelocity(double minVelocity, double maxVelocity,
                            double acceleration) override;
    asynStatus home(double minVelocity, double maxVelocity,
                    double acceleration, int forwards) override;
    asynStatus stop(double acceleration) override;
    asynStatus poll(bool* moving) override;
    asynStatus setPosition(double position) override;
    asynStatus setSelectedHomeMethod(int method);

private:
    KohzuAriesLynxController* controller_;
    int controllerAxisNo_;
    KohzuAxisSnapshot snapshot_;
    bool hasSnapshot_;
    int selectedHomeMethod_;

    friend class KohzuAriesLynxController;
};

class KohzuAriesLynxController : public asynMotorController {
public:
    KohzuAriesLynxController(const char* portName, const char* ioPortName,
                             int numAxes, double movingPollPeriod,
                             double idlePollPeriod);
    ~KohzuAriesLynxController() override;

    KohzuAriesLynxAxis* getAxis(asynUser* pasynUser) override;
    KohzuAriesLynxAxis* getAxis(int axisNo) override;
    void report(FILE* fp, int details) override;
    asynStatus writeInt32(asynUser* pasynUser, epicsInt32 value) override;

    // These queries do not move an axis or change controller settings.
    asynStatus readIdentity(std::string* identity);
    asynStatus readAxisConfiguration(int* detectedAxes);
    asynStatus readAxisSnapshot(int controllerAxisNo,
                                KohzuAxisSnapshot* snapshot);

    // Request a normal decelerating stop. This deliberately does not expose
    // the controller's emergency-stop mode or release either EMG lock type.
    asynStatus stopAxis(int controllerAxisNo);
    asynStatus configureSpeedTable0(int controllerAxisNo,
                                    double minVelocity,
                                    double maxVelocity,
                                    double acceleration);
    asynStatus setSelectedHomeMethod(int controllerAxisNo, int method);
    asynStatus homeAxis(int controllerAxisNo, int selectedMethod,
                        double minVelocity, double maxVelocity,
                        double acceleration);
    asynStatus moveAxis(int controllerAxisNo, double position, bool relative,
                        double minVelocity, double maxVelocity,
                        double acceleration, double lowLimit,
                        double highLimit);
    asynStatus jogAxis(int controllerAxisNo, double minVelocity,
                       double maxVelocity, double acceleration,
                       double lowLimit, double highLimit);
    asynStatus setAxisPosition(int controllerAxisNo, double position);

private:
    asynStatus transact(const std::string& command,
                        const std::string& expectedResponse,
                        KohzuResponse* response);
    void updateDiagnostic(const KohzuResponse& response);
    asynStatus readEmergencyStopState(int controllerAxisNo, bool* active);
    asynStatus releaseEmergencyStop();
    asynStatus refreshAxisConfiguration();
    void recordAxisEmergencyState(int controllerAxisNo, bool active);
    void setRecoveryStatus(const std::string& text);

    std::string ioPortName_;
    std::string identity_;
    int detectedAxes_;
    asynStatus connectionStatus_;
    KohzuResponse lastSystemEvent_;

    int lastErrorCode_;
    int lastErrorText_;
    int lastErrorCommand_;
    int lastErrorRaw_;
    int lastWarningCode_;
    int lastWarningText_;
    int lastWarningCommand_;
    int lastWarningRaw_;
    int emergencyActive_;
    int recoveryRemRequest_;
    int recoveryRaxRequest_;
    int recoveryStatus_;
    int selectedHomeMethodParam_;
    int actualHomeMethodParam_;
    int homeStatusParam_;
    int moveStatusParam_;
    int positionStatusParam_;
    std::vector<bool> emergencyStates_;

    friend class KohzuAriesLynxAxis;
};

#endif
