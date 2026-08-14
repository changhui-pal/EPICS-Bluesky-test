# Apply only the user-selected initial methods after iocInit. Sensor
# suitability is checked by the user, not enforced by the IOC.
dbpf "$(KOHZU_PREFIX=KOHZU:)m1:OriginMethod" 4
dbpf "$(KOHZU_PREFIX=KOHZU:)m2:OriginMethod" 4
dbpf "$(KOHZU_PREFIX=KOHZU:)m3:OriginMethod" 10
dbpf "$(KOHZU_PREFIX=KOHZU:)m4:OriginMethod" 4
dbpf "$(KOHZU_PREFIX=KOHZU:)m5:OriginMethod" 10
