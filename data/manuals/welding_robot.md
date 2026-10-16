# Welding Robot Cell – Technician Manual

Applies to the six-axis MIG/MAG welding robot cell with wire feeder, torch cleaning station and tip dresser.
All work described here is for trained maintenance technicians only.

## Wire Feed Jam

**Symptoms**
- Robot stops in the middle of a weld seam and the arc goes out.
- Wire feeder motor runs but the wire does not advance, or the wire bird-nests at the drive rollers.
- Irregular, porous seams on the last parts before the stop.

**Related error codes:** E101 (Wire feed jam)

**Step-by-step fix**
1. Stop the robot program and move the robot to the service position with the teach pendant.
2. Apply lockout/tagout (see safety note) and let the torch cool down for at least 10 minutes.
3. Cut the wire at the contact tip and pull the wire back to the feeder.
4. Open the feeder and inspect the drive rollers. Replace rollers with a flattened or worn groove; check that the groove size matches the wire diameter (1.0 mm or 1.2 mm).
5. Remove the wire liner from the torch hose package. Blow it out with dry compressed air from the feeder side. Replace the liner if it is kinked, crushed or longer than 6 months in service.
6. Check the hose package for tight bends around axis 4 and axis 6. Re-route it so the bend radius is at least 200 mm.
7. Reinstall the liner, trim it to the specified length, and fit a new contact tip.
8. Set the roller pressure to the marking for the wire type. Too much pressure deforms the wire, too little causes slip.
9. Feed the wire through manually, remove lockout/tagout, and run one test seam on a scrap part.

**Safety note:** Apply lockout/tagout before any work: switch off the robot controller and the welding power source, lock the main disconnect and attach your personal tag. The torch neck can be above 300 °C after welding. Wear cut-resistant gloves when handling wire.

## Weld Current Out of Tolerance

**Symptoms**
- Weld monitor reports current outside the allowed band; seams show spatter or lack of fusion.
- Unstable arc sound, frequent arc restarts.

**Related error codes:** E102 (Weld current out of tolerance)

**Step-by-step fix**
1. Stop the cell and apply lockout/tagout.
2. Remove the gas nozzle and contact tip. Replace the contact tip if the bore is oval or has spatter build-up.
3. Clean the gas nozzle and check the gas diffuser for blocked holes.
4. Inspect the ground (work return) cable and clamp on the fixture. Clean the contact surfaces down to bare metal and tighten the clamp bolt.
5. Check the power cable connections on the power source for discoloration or heat damage.
6. Remove lockout/tagout, run a test seam and compare the logged current with the weld procedure specification.
7. If the deviation remains, record the values and escalate to the process engineer; do not change the weld parameters on your own.

**Safety note:** Apply lockout/tagout before any work on the torch or ground path. Never touch the contact tip or the wire while the power source is energized.

## Torch Collision

**Symptoms**
- Robot performs an emergency stop and the collision sensor (breakaway clutch) is triggered.
- Torch neck is visibly bent, or the wire no longer points at the seam start.
- Parts in the fixture are out of position or missing clamps.

**Related error codes:** E103 (Torch collision detected)

**Step-by-step fix**
1. Do not reset the alarm and restart immediately. First find the cause.
2. Apply lockout/tagout, then enter the cell.
3. Check the part in the fixture: is it seated against all locators and are all clamps closed? Remove misplaced parts.
4. Inspect the torch neck and the breakaway clutch. Replace a bent torch neck; do not bend it back.
5. Check the fixture locators and clamp pads for wear or loose bolts.
6. Leave the cell, remove lockout/tagout, and reset the collision sensor.
7. Run the tool center point (TCP) check program. If the TCP deviates by more than 0.5 mm, recalibrate the TCP before production.
8. Run the program in reduced speed (T1) through the collision area and watch the torch path.
9. If collisions repeat at the same point, report a possible robot path drift to the robot programmer.

**Safety note:** Apply lockout/tagout before entering the cell. A robot stopped by a collision can still hold stored energy in the breakaway clutch spring; keep hands away from the torch until it is released.

## Tip Dressing Overdue

**Symptoms**
- Controller shows a maintenance reminder; seam quality slowly decreases.
- Contact tip and nozzle have heavy spatter build-up.

**Related error codes:** E104 (Tip dressing overdue)

**Step-by-step fix**
1. Check the tip dresser counter in the robot controller and confirm when the last dressing cycle ran.
2. Apply lockout/tagout and inspect the dresser cutter blade. Replace a chipped or dull blade.
3. Clean spatter from the dresser housing and the anti-spatter spray nozzle; refill anti-spatter fluid.
4. Remove lockout/tagout and run the dressing cycle manually once.
5. Reset the counter. If the cycle was skipped by the program, inform the robot programmer so the call is added back to the main program.

**Safety note:** Apply lockout/tagout before touching the tip dresser. The cutter blade turns at high speed and starts without warning when the robot calls the cycle.
