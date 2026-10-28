; Event graph of /Game/Test/BP_TestCharacter. Polls keys every tick so no input mapping file is needed.
; Apply with MCP: BlueprintTools.write_graph_dsl(graph=<BP>:EventGraph, code=<this file>), then run test_character_gamemode.py.
; Speeds are the measured ones (analysis/CHARACTER-PROBE.md): walk 510, sprint 688.5 (x1.35). Crouch speed 200 is a CharacterMovement default set by test_character_base.py.
; Mouse sensitivity is the instance-editable variable MouseSensitivity (category Test, default 0.1 deg per count) and the keys (WASD, Shift, Ctrl, Space) are our choices, not measured.
(event EventTick (DeltaSeconds)
  (bind pc (Game|GetPlayerController :PlayerIndex 0))
  (bind ms (Variables|Test|GetMouseSensitivity))
  (bind cm (Variables|Character|GetCharacterMovement))
  (bind kw (select (Game|Player|IsInputKeyDown pc "W") 1.0 0.0))
  (bind ks (select (Game|Player|IsInputKeyDown pc "S") 1.0 0.0))
  (bind kd (select (Game|Player|IsInputKeyDown pc "D") 1.0 0.0))
  (bind ka (select (Game|Player|IsInputKeyDown pc "A") 1.0 0.0))
  (Pawn|Input|AddMovementInput :WorldDirection (Transformation|GetActorForwardVector) :ScaleValue (- kw ks))
  (Pawn|Input|AddMovementInput :WorldDirection (Transformation|GetActorRightVector) :ScaleValue (- kd ka))
  (bind (dx dy) (Game|Player|GetInputMouseDelta pc))
  (Pawn|Input|AddControllerYawInput :Val (* dx ms))
  (Pawn|Input|AddControllerPitchInput :Val (* dy (neg ms)))
  (Class|CharacterMovementComponent|SetMaxWalkSpeed :self cm :MaxWalkSpeed (select (Game|Player|IsInputKeyDown pc "LeftShift") 688.5 510.0))
  (if (Game|Player|IsInputKeyDown pc "LeftControl")
    (Character|Crouch)
    (else (Character|UnCrouch)))
  (if (Game|Player|IsInputKeyDown pc "SpaceBar")
    (Character|Jump)
    (else (Character|StopJumping))))
