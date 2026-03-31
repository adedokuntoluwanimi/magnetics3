## Processing Audit

The processing pipeline now runs in these explicit stages:

1. load and validate
2. clean and standardize
3. line-domain corrections
4. leveling and crossover
5. prediction target preparation
6. modelling and interpolation
7. grid-domain transforms
8. uncertainty synthesis
9. QA report generation
10. output packaging and persistence

### Line-domain operations

- spike handling
- IGRF removal when `pyIGRF` is available
- diurnal correction from base-station interpolation, with explicit FFT or median fallbacks
- lag correction from line-wise cross-correlation with confidence gating
- heading correction from smoothed `atan2` headings and adaptive bins
- crossover-based leveling

### Grid-domain operations

- magnetic surface generation
- uncertainty synthesis
- RTP or fallback mean-centred surface
- analytic signal
- first vertical derivative
- horizontal derivative
- regional residual
- continuation products when requested

### QA outputs

Each run now stores:

- validation summary
- fallback events
- stage reports
- crossover metrics
- model diagnostics
- integrity checks
- overall QA status

### Naming rules

- `Regional residual` is the honest label for the former `EMAG2 comparison` output unless an actual EMAG2 reference dataset is introduced.
- `Hybrid` means RF trend plus kriged residuals when available; otherwise the fallback is recorded in QA metadata.
- RTP metadata must record when inclination/declination were missing and a fallback was used.
