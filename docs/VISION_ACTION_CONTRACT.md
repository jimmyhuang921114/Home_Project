# Vision Action Contract Governance

`Home_Project/src/Home_Project/semantic_nav_interfaces` is the sole authoritative source for the semantic vision Action contract.

1. Home_Project `semantic_nav_interfaces` is the only formal contract source.
2. Thor must not directly modify its synchronized IDL copy.
3. Every contract change starts in Home_Project.
4. A change may be synchronized to Thor only after Home_Project build and contract tests pass.
5. Home_Project and Thor IDL SHA-256 values must match after synchronization.
6. The interface package version must match on both sides.
7. Generated Python fields and `ros2 interface show` output must match.
8. `hasattr`, duck typing, or ignored fields must not mask incompatible contracts.
9. Breaking compatibility requires an interface version increase.
10. Runtime metadata must record the Home_Project Git commit and both IDL SHA-256 values.

The initial `0.1.0` files were bootstrapped once from the Thor contract that passed ROS 2 Action loopback validation. After that bootstrap, synchronization is strictly Home_Project → Thor via `scripts/sync_semantic_nav_interfaces_from_home_project.sh`.
