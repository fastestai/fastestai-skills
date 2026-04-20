# QC Rubric

This skill evaluates generated fashion images against reference images using six dimensions.

## Identity

Compare the generated result against the model reference.

- `model_face`: facial identity and recognizable appearance
- `makeup_hair`: makeup style and hairstyle consistency
- `body_skin_tone`: body shape and skin tone consistency without obvious distortion
- `skin_evenness`: skin should look natural and reasonably even

## Garment

Compare the generated result against the garment reference.

- `garment_shape`: garment silhouette, cut, and structure
- `pattern_details`: prints, seams, buttons, and other visible details
- `material_texture`: fabric feel, sheen, thickness, surface grain, and drape behavior
- `transparency_distribution`: where the garment is transparent versus opaque, including lining and sheer layer placement
- `hem_length_and_edge`: visible hem length, lower edge shape, and lower-layer behavior
- `garment_color`: main color fidelity and obvious color cast
- `wearing_naturalness`: fit, drape, and absence of clipping or deformation

## Pose

Compare the generated result against the pose reference.

- `overall_pose`: overall stance or seated pose
- `hand_head_details`: hands, arms, head angle, and local gesture details
- `framing_proportion`: subject placement, framing, and rough body proportion in the scene

## Background

Compare the generated result against the background reference.

- `background_content`: scene type and major elements
- `background_tone`: overall color tone and mood
- `background_texture`: texture and detail preservation without obvious over-blur or oversharpening
- `background_lighting`: light direction, brightness, and strength

## Fusion

Evaluate whether the result image feels composited cleanly and consistently.

- `edge_blending`: no obvious halo, jagged cutout edge, floating subject, or bad masking
- `lighting_consistency`: subject lighting should not visibly conflict with scene lighting

## Quality

Evaluate the generated result image alone.

- `base_image_quality`: no obvious blur, blocky artifacts, severe noise, or broken regions

## Status rules

- `pass`: no visible material issue for the requested item
- `fail`: a visible, material issue exists
- `uncertain`: the image evidence is insufficient or ambiguous
- `missing_input`: the evaluator cannot run because required role images are missing
- `not_applicable`: reserved for future flows with intentionally skipped dimensions

Prefer `uncertain` over guessing.
Fail only on visible and meaningful defects, not minor aesthetic preference.
