# Copernicus CMIP6 Processing

Bulk download, process, validate, and plot CMIP6 climate model anomalies for a location (New York example included).

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:
   - `pip install -r requirements.txt`
3. Ensure your CDS API credentials exist at `~/.cdsapirc` and accept CMIP6 Terms of Use.

## Data Source

CMIP6 data is accessed from the Copernicus Climate Data Store (CDS):
- **URL**: https://cds.climate.copernicus.eu/
- **Dataset**: CMIP6 monthly data on single levels
- **Variables**: Monthly minimum and maximum temperature, and temperature anomalies (bias-corrected)
- **Scenarios**: Historical (1850–2014) and future projections (SSP1-2.6, SSP2-4.5, SSP5-8.5; 2015–2300)

## Bulk Workflow (Notebook)

Open [cmip6_bulk_download_newyork.ipynb](cmip6_bulk_download_newyork.ipynb) and run the cells in order.

Key steps:

- **Download only**: downloads raw model files
- **Process only**: creates per-model anomalies, combined per-model outputs, and summary
- **Plot only**: generates the grid plot from existing outputs
- **Combine only**: creates location-wide all-model anomaly files

## Command-Line Workflow

### Download only
```
python download_all_models.py --location NewYork --area 45 -75 40 -70 --download-dir CMIP6 --download-only
```

### Process only
```
python download_all_models.py --location NewYork --area 45 -75 40 -70 --download-dir CMIP6 --process-only
```

### Plot only
```
python download_all_models.py --location NewYork --area 45 -75 40 -70 --download-dir CMIP6 --plot-only
```

### Combine only (location-wide files)
```
python download_all_models.py --location NewYork --area 45 -75 40 -70 --download-dir CMIP6 --combine-only --max-year 2100
```

## Outputs

Per-model outputs (stored under `CMIP6/<Location>/<Model>/`):

- `cmip6_<model>_temperature_anomalies_all_scenarios_1961-1990baseline.nc`
- `cmip6_<model>_temperature_anomalies_JJA_all_scenarios_1961-1990baseline.nc`

Location-wide combined outputs (stored under `CMIP6/<Location>/`):

- `<Location>_temperature_anomalies_all_models_1961-1990baseline.nc`
- `<Location>_temperature_anomalies_JJA_all_models_1961-1990baseline.nc`

Plots:

- `CMIP6/<Location>_plots_avg.png`

Summary:

- `CMIP6/<Location>_summary.csv`

## Single Model Notebook

Use [cmip6_single_model_newyork.ipynb](cmip6_single_model_newyork.ipynb) for a focused download of one CMIP6 model.

## Citations & Terms of Use

When using CMIP6 data in published work, you must comply with the CMIP6 Terms of Use and cite the data appropriately.

### Key Requirements

- **License**: CMIP6 data is licensed under Creative Commons Attribution 4.0 International (CC BY 4.0). As of October 2022, all contributing modeling groups have adopted this relaxed license.
- **Citation**: You must cite CMIP6 model output as required by the CMIP6 Data Citation Guidelines.
- **Acknowledgment**: Include acknowledgment language in your publication: "We acknowledge the World Climate Research Programme, which, through its Working Group on Coupled Modelling, coordinated and promoted CMIP6. We thank the climate modeling groups for producing and making available their model output, the Earth System Grid Federation (ESGF) for archiving the data and providing access, and the multiple funding agencies who support CMIP6 and ESGF."
- **Model/Institution Table**: Include a table listing the models and institutions that provided model output used in your research, using official CMIP6 model names and institution IDs.
- **Archive Terminology**: Refer to the collection as the "CMIP6 multi-model ensemble" and use phrases like "CMIP6 multi-model [archive/output/results/simulations/dataset/…]".

### Citation Format

**Copernicus CDS Catalogue Entry**:

> Copernicus Climate Change Service, Climate Data Store, (2021): CMIP6 climate projections. Copernicus Climate Change Service (C3S) Climate Data Store (CDS). DOI: 10.24381/cds.c866074c (Accessed on DD-MMM-YYYY)

### Additional Resources

- **CMIP6 Terms of Use**: https://pcmdi.llnl.gov/CMIP6/TermsOfUse
- **CMIP6 CDS Catalogue**: https://cds.climate.copernicus.eu/
- **CMIP6 Publications Registry**: https://pcmdi.llnl.gov/CMIP6/
- **ESGF Data Portal**: https://esgf-node.llnl.gov/projects/cmip6/


