# Automatic Screwdriving Station – Technician Manual

Applies to the automatic screwdriving station with electric nutrunner, torque/angle controller and vibratory screw feeder.
All work described here is for trained maintenance technicians only.

## Torque Out of Range

**Symptoms**
- Controller reports NOK screw joints; final torque or angle outside the limits.
- Screws are stripped, cross-threaded or not seated flush.
- Bit slips out of the screw head (cam-out) and leaves marks.

**Related error codes:** E401 (Torque out of range)

**Step-by-step fix**
1. Stop the station and set NOK parts aside for quality inspection.
2. Apply lockout/tagout.
3. Remove the bit and check the tip under a magnifier. Replace a bit with rounded or chipped edges.
4. Check the bit holder and the spindle for play.
5. Check the screw batch label against the bill of materials. Wrong length, head type or coating changes the torque.
6. Inspect the part threads for damage or contamination.
7. Remove lockout/tagout and run the transducer check with the reference joint. If the measured torque differs by more than 5 % from the controller value, the nutrunner must be recalibrated.
8. Run five test joints and confirm all are OK before restarting production.

**Safety note:** Apply lockout/tagout before any work on the spindle or bit. The spindle can start automatically when a part is detected.

## Screw Feeder Empty

**Symptoms**
- Station waits for a screw; feed tube empty.
- Feeder bowl low-level sensor active.

**Related error codes:** E402 (Screw feeder empty)

**Step-by-step fix**
1. Check the screw type on the bin label against the label on the feeder.
2. Refill the feeder bowl up to the fill mark. Do not overfill; this causes screws to jam in the bowl track.
3. If the bowl is full but no screws arrive, apply lockout/tagout and check the feed tube and the separator for a jammed screw.
4. Remove foreign screws or broken parts from the bowl track.
5. Remove lockout/tagout and check that screws are delivered to the nosepiece.
6. Inform the line logistics if refills are repeatedly late.

**Safety note:** Apply lockout/tagout before reaching into the separator or the feed tube. The pneumatic separator can move without warning while air pressure is applied; vent the air supply as part of the lockout.
