# Repeatable user-requested AD5X job clearing

Owner: the print-buddy profile only. Use `python3 -m print_buddy.core.clear_job`. Other profiles never contact the printer.

Read-only verification: python3 -m print_buddy.core.clear_job --check --evidence <durable JSON path>.

When the operator explicitly asks to cancel/clear an existing job, python3 -m print_buddy.core.clear_job --allow-active-cancel --evidence <durable JSON path> permits one supported Moonraker cancel, including contradictory native printing/Moonraker standby states. This flag is NOT standing permission for automatic cancellation. Default refuses active jobs. Already canceled and corroborated idle is a no-op. No retries after uncertain acceptance. No heating, restart, calibration or filament changes.

Receipt and native/Moonraker before/after state are saved. Success requires zero native and Moonraker heater targets, Moonraker standby/ready, and native cancel/cancelled following a sent cancel. Retained filename does not imply active printing and is not deleted by this operation. Missing source/readback or uncertain cancel must be reported as unresolved, not success. Helper cancellation execution has not been physically exercised; earlier manually supported cancellation did clear the original state, but this helper has only offline coverage.

Code fixes do not establish physical slot routing. Logical T0 to physical slot mapping must be verified before use. Do not use SET_EXTRUDER_SLOT as a load command or assume a tool number equals a slot.
