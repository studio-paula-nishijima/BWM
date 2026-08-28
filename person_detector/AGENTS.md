# Vision-node workspace routing

For physical ESP-IDF builds and flashes on the user's Windows workstation, use
the stable primary hardware folder:

`BWM-review/person_detector/stage2_espidf`

Implementation and publishing must still follow the root workspace rules and
use the task's named worktree. Before handing a firmware build or flash back to
the user, mirror every changed vision-node firmware file from that worktree into
the stable primary hardware folder. Also mirror the deployment-local, ignored
`mqtt_config.h` when its settings change. When `sdkconfig.defaults` changes,
also ensure the stable folder's ignored generated `sdkconfig` contains the new
settings; `idf.py fullclean` does not regenerate that file or apply newly added
defaults. Mirror a verified task-worktree `sdkconfig` or regenerate it in the
stable folder before handoff. Never mirror or modify files outside
`person_detector/`, and preserve the primary checkout's unrelated changes.

Build and flash instructions for the user must continue to start from the
stable primary hardware folder, not from an ephemeral `.worktrees` path. Confirm
that the mirrored source contains the expected stage endpoints/features and
that `mqtt_config.h` contains the intended broker and required Bluetooth/Wi-Fi
options are active in `sdkconfig` before telling the user to flash. Git commits,
rebases, and pushes must still be performed from the task
worktree, never from the dirty primary checkout.
