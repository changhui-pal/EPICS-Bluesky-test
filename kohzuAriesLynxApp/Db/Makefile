TOP=../..
include $(TOP)/configure/CONFIG
#----------------------------------------
#  ADD MACRO DEFINITIONS AFTER THIS LINE

#----------------------------------------------------
# Create and install (or just install) into <top>/db
# databases, templates, substitutions like this
DB += kohzuAriesLynxMotors.substitutions
DB += kohzuAriesLynxDiagnostics.db
DB += kohzuAriesLynxHomeDiagnostics.template
DB += kohzuAriesLynxHomeDiagnostics.substitutions
DB += kohzuAriesLynxCommissioning.template
DB += kohzuAriesLynxCommissioning.substitutions
DB += kohzuAriesLynxAccessSecurity.acf
DB += kohzuAsynMotor.template

#----------------------------------------------------
# If <anyname>.db template is not named <anyname>*.template add
# <anyname>_template = <templatename>

include $(TOP)/configure/RULES
#----------------------------------------
#  ADD RULES AFTER THIS LINE
