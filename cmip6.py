#!/usr/bin/env python3
"""
CMIP6 Climate Data Download Script

This script downloads CMIP6 projections data for North Carolina.

Before running:
1. Ensure ~/.cdsapirc is configured with your CDS API credentials
2. Accept the Terms of Use for CMIP6 data on the CDS website
"""

import os
import zipfile
from pathlib import Path

import cdsapi
import pandas as pd
import xarray as xr


def generate_year_range(start_year, end_year):
    """Generate a list of years as strings."""
    return [str(year) for year in range(start_year, end_year + 1)]


def normalize_model_id(name: str) -> str:
    """Normalize model name to CDS API format."""
    return name.strip().lower().replace("-", "_").replace(" ", "_")


def sanitize_filename(name: str) -> str:
    """Sanitize model name for use in filenames."""
    return name.strip().replace(" ", "_")


def sniff_file_type(path: Path) -> str:
    """Detect file type by magic bytes."""
    with open(path, "rb") as f:
        sig = f.read(4)
    if sig.startswith(b"PK"):
        return "zip"
    if sig.startswith(b"\x1f\x8b"):
        return "gzip"
    return "netcdf"


def open_dataset_auto(path: Path, download_dir: Path = None):
    """Open NetCDF dataset, extracting from zip if needed."""
    ftype = sniff_file_type(path)
    if ftype == "zip":
        if download_dir is None:
            download_dir = path.parent
        with zipfile.ZipFile(path, "r") as zf:
            nc_members = [n for n in zf.namelist() if n.lower().endswith(".nc")]
            if not nc_members:
                raise ValueError("Zip file does not contain a .nc file")
            extracted = download_dir / Path(nc_members[0]).name
            zf.extract(nc_members[0], path=download_dir)
            return xr.open_dataset(extracted, engine="netcdf4", use_cftime=True)
    if ftype == "gzip":
        raise ValueError("Gzip file detected. Please decompress it before loading.")
    return xr.open_dataset(path, engine="netcdf4", use_cftime=True)


def combine_experiments(
    model_dir: Path, variable: str, file_model: str, experiments: dict
):
    """Combine multiple experiment files into a single NetCDF."""
    datasets = []
    experiment_labels = []

    for exp in experiments.keys():
        start_year, end_year = experiments[exp]
        output_name = f"cmip6_{variable}_{file_model}_{exp}_{start_year}-{end_year}.nc"
        exp_path = model_dir / output_name

        if exp_path.exists():
            try:
                ds_exp = open_dataset_auto(exp_path, download_dir=model_dir)
                datasets.append(ds_exp)
                experiment_labels.extend([exp] * len(ds_exp.time))
                print(f"Loaded {exp}: {len(ds_exp.time)} timesteps")
            except Exception as e:
                print(f"Error loading {exp}: {e}")
        else:
            print(f"File not found for {exp}: {exp_path}")

    if datasets:
        combined_ds = xr.concat(datasets, dim="time")
        combined_ds["experiment"] = ("time", experiment_labels)
        combined_ds["experiment"].attrs["description"] = "CMIP6 experiment identifier"

        combined_file = (
            model_dir / f"cmip6_{variable}_{file_model}_combined_1850-2300.nc"
        )
        combined_ds.to_netcdf(combined_file)
        print(f"\n✓ Combined file saved: {combined_file}")
        print(f"  Total timesteps: {len(combined_ds.time)}")
        time_years = combined_ds["time"].dt.year
        print(
            f"  Time range: {int(time_years.min().values)} - {int(time_years.max().values)}"
        )
        return combined_file
    else:
        print("No datasets loaded to combine.")
        return None


def combine_historical_with_scenarios(
    model_dir: Path, variable: str, file_model: str, experiments: dict
):
    """
    Combine historical data with each SSP scenario to create continuous timelines.
    Creates separate files for historical+ssp126, historical+ssp245, historical+ssp585.
    
    Args:
        model_dir: Directory containing the experiment files.
        variable: Variable name (tasmax or tasmin).
        file_model: Sanitized model name.
        experiments: Dictionary of experiment years.
    
    Returns:
        List of paths to the combined scenario files.
    """
    # Load historical data
    hist_start, hist_end = experiments["historical"]
    hist_file = model_dir / f"cmip6_{variable}_{file_model}_historical_{hist_start}-{hist_end}.nc"
    
    if not hist_file.exists():
        print(f"Historical file not found: {hist_file}")
        return []
    
    ds_historical = open_dataset_auto(hist_file, download_dir=model_dir)
    print(f"Loaded historical: {len(ds_historical.time)} timesteps")
    
    combined_files = []
    
    # Combine historical with each SSP scenario
    for exp in ["ssp126", "ssp245", "ssp585"]:
        if exp not in experiments:
            continue
            
        ssp_start, ssp_end = experiments[exp]
        ssp_file = model_dir / f"cmip6_{variable}_{file_model}_{exp}_{ssp_start}-{ssp_end}.nc"
        
        if not ssp_file.exists():
            print(f"File not found for {exp}: {ssp_file}")
            continue
        
        ds_ssp = open_dataset_auto(ssp_file, download_dir=model_dir)
        print(f"Loaded {exp}: {len(ds_ssp.time)} timesteps")
        
        # Concatenate historical + SSP along time dimension
        combined = xr.concat([ds_historical, ds_ssp], dim="time")
        
        # Add scenario label as attribute
        combined.attrs["scenario"] = f"historical+{exp}"
        
        # Save combined file
        output_file = model_dir / f"cmip6_{variable}_{file_model}_historical+{exp}_1850-2300.nc"
        combined.to_netcdf(output_file)
        combined_files.append(output_file)
        
        print(f"✓ Saved {output_file.name}")
        print(f"  Total timesteps: {len(combined.time)}")
    
    return combined_files


def compute_anomalies(ds, baseline_start_year=1961, baseline_end_year=1990):
    """
    Compute anomalies by subtracting the mean of a baseline period.
    
    Args:
        ds: xarray Dataset with a time dimension and variables.
        baseline_start_year: Start year of baseline period (default 1961).
        baseline_end_year: End year of baseline period (default 1990).
    
    Returns:
        xarray Dataset with anomalies computed for all data variables.
    """
    # Sort by time to ensure monotonic index for slicing
    ds_sorted = ds.sortby("time")
    ds_anom = ds_sorted.copy()
    
    # Check if experiment dimension exists (from combined files)
    if "experiment" in ds.dims:
        # Select only historical experiment for baseline (should contain baseline years)
        baseline = ds_sorted.sel(experiment="historical")
        baseline = baseline.where(
            (baseline["time"].dt.year >= baseline_start_year)
            & (baseline["time"].dt.year <= baseline_end_year),
            drop=True,
        )
    else:
        # No experiment dimension, select directly
        baseline = ds_sorted.where(
            (ds_sorted["time"].dt.year >= baseline_start_year)
            & (ds_sorted["time"].dt.year <= baseline_end_year),
            drop=True,
        )
    
    # Compute mean for each data variable (skip bounds and other non-climate variables)
    for var in ds_sorted.data_vars:
        # Skip bounds variables and other auxiliary variables
        if var.endswith("_bnds") or var.endswith("_bounds"):
            continue
        
        # Only process variables that have a time dimension
        if "time" not in ds_sorted[var].dims:
            continue
        
        # Only process numeric data (skip string/object dtypes)
        var_dtype = ds_sorted[var].dtype
        if var_dtype.kind not in ['f', 'i', 'u']:  # float, int, unsigned int
            print(f"⊘ Skipping {var} (non-numeric dtype: {var_dtype})")
            continue
        
        baseline_mean = baseline[var].mean(dim="time")
        ds_anom[var] = ds_sorted[var] - baseline_mean
        print(f"✓ Computed anomalies for {var} (baseline: {baseline_start_year}-{baseline_end_year})")
    
    return ds_anom


def compute_seasonal_anomalies(
    ds,
    months=None,
    baseline_start_year=1961,
    baseline_end_year=1990,
):
    """
    Compute seasonal (e.g., JJA) anomalies by first averaging over selected months
    within each year and then subtracting the baseline seasonal mean.

    Args:
        ds: xarray Dataset with a time dimension and variables.
        months: List of month numbers to include (default JJA: [6, 7, 8]).
        baseline_start_year: Start year of baseline period (default 1961).
        baseline_end_year: End year of baseline period (default 1990).

    Returns:
        xarray Dataset with anomalies computed for selected months, grouped by year.
    """
    if months is None:
        months = [6, 7, 8]

    # Sort by time to ensure monotonic index for slicing
    ds_sorted = ds.sortby("time")

    # Select months and compute seasonal mean per year
    ds_season = ds_sorted.sel(time=ds_sorted["time"].dt.month.isin(months))
    ds_yearly = ds_season.groupby("time.year").mean("time")

    ds_anom = ds_yearly.copy()

    # Baseline selection on year dimension
    baseline = ds_yearly.sel(year=slice(baseline_start_year, baseline_end_year))

    for var in ds_yearly.data_vars:
        if var.endswith("_bnds") or var.endswith("_bounds"):
            continue
        if "year" not in ds_yearly[var].dims:
            continue
        var_dtype = ds_yearly[var].dtype
        if var_dtype.kind not in ["f", "i", "u"]:
            print(f"⊘ Skipping {var} (non-numeric dtype: {var_dtype})")
            continue

        baseline_mean = baseline[var].mean(dim="year")
        ds_anom[var] = ds_yearly[var] - baseline_mean
        print(
            f"✓ Computed seasonal anomalies for {var} "
            f"(months: {months}, baseline: {baseline_start_year}-{baseline_end_year})"
        )

    return ds_anom


def average_tasmax_tasmin(tasmax_ds, tasmin_ds):
    """
    Average tasmax and tasmin datasets together.
    
    Assumes both datasets have the same time dimension and spatial structure.
    
    Args:
        tasmax_ds: xarray Dataset with tasmax variable.
        tasmin_ds: xarray Dataset with tasmin variable.
    
    Returns:
        xarray Dataset with a single 'temperature' variable (average of tasmax and tasmin).
    """
    # Extract the temperature variables (usually named after the input variable names)
    tasmax_var = [v for v in tasmax_ds.data_vars if v in ["tasmax", "daily_maximum_near_surface_air_temperature"]][0]
    tasmin_var = [v for v in tasmin_ds.data_vars if v in ["tasmin", "daily_minimum_near_surface_air_temperature"]][0]
    
    # Compute average
    avg_temp = (tasmax_ds[tasmax_var] + tasmin_ds[tasmin_var]) / 2
    
    # Create new dataset with the average
    # The coords from tasmax_ds already include experiment if it exists
    result = xr.Dataset(
        {"temperature": avg_temp},
        coords=tasmax_ds.coords,
        attrs={"description": "Average of tasmax and tasmin anomalies"}
    )
    
    print(f"✓ Computed average temperature (tasmax + tasmin) / 2")
    
    return result


def _combine_scenarios_to_file(datasets_by_scenario, output_path):
    scenarios = [s for s in datasets_by_scenario.keys()]
    if not scenarios:
        return None
    combined = xr.concat([datasets_by_scenario[s] for s in scenarios], dim="scenario")
    combined = combined.assign_coords(scenario=scenarios)
    combined.to_netcdf(output_path)
    return output_path


def process_scenarios_anomalies(
    model_dir: Path,
    file_model: str,
    scenarios=None,
    baseline_start_year: int = 1961,
    baseline_end_year: int = 1990,
    months=None,
):
    """
    Process historical+scenario files to produce anomaly datasets and save outputs.

    Creates per-scenario monthly anomaly files and per-scenario seasonal anomaly files
    (default JJA), plus combined files that include all scenarios.

    Args:
        model_dir: Directory with combined historical+scenario files.
        file_model: Sanitized model name.
        scenarios: List of scenarios (default ["ssp126", "ssp245", "ssp585"]).
        baseline_start_year: Baseline start year.
        baseline_end_year: Baseline end year.
        months: Month list for seasonal anomalies (default JJA [6, 7, 8]).

    Returns:
        Dict with keys: monthly, seasonal, combined_monthly, combined_seasonal.
    """
    if scenarios is None:
        scenarios = ["ssp126", "ssp245", "ssp585"]
    if months is None:
        months = [6, 7, 8]

    monthly = {}
    seasonal = {}

    for scenario in scenarios:
        tasmax_file = model_dir / f"cmip6_tasmax_{file_model}_historical+{scenario}_1850-2300.nc"
        tasmin_file = model_dir / f"cmip6_tasmin_{file_model}_historical+{scenario}_1850-2300.nc"

        if not tasmax_file.exists() or not tasmin_file.exists():
            print(f"Missing files for {scenario}")
            continue

        ds_tasmax = open_dataset_auto(tasmax_file, download_dir=model_dir)
        ds_tasmin = open_dataset_auto(tasmin_file, download_dir=model_dir)

        ds_tasmax_anom = compute_anomalies(
            ds_tasmax,
            baseline_start_year=baseline_start_year,
            baseline_end_year=baseline_end_year,
        )
        ds_tasmin_anom = compute_anomalies(
            ds_tasmin,
            baseline_start_year=baseline_start_year,
            baseline_end_year=baseline_end_year,
        )
        ds_avg_anom = average_tasmax_tasmin(ds_tasmax_anom, ds_tasmin_anom)
        monthly[scenario] = ds_avg_anom

        monthly_file = model_dir / (
            f"cmip6_{file_model}_temperature_anomalies_historical+{scenario}_"
            f"{baseline_start_year}-{baseline_end_year}baseline.nc"
        )
        ds_avg_anom.to_netcdf(monthly_file)
        print(f"✓ Saved {monthly_file.name}")

        ds_avg_raw = average_tasmax_tasmin(ds_tasmax, ds_tasmin)
        ds_avg_seasonal_anom = compute_seasonal_anomalies(
            ds_avg_raw,
            months=months,
            baseline_start_year=baseline_start_year,
            baseline_end_year=baseline_end_year,
        )
        seasonal[scenario] = ds_avg_seasonal_anom

        seasonal_label = "JJA" if months == [6, 7, 8] else "months"
        seasonal_file = model_dir / (
            f"cmip6_{file_model}_temperature_anomalies_{seasonal_label}_historical+{scenario}_"
            f"{baseline_start_year}-{baseline_end_year}baseline.nc"
        )
        ds_avg_seasonal_anom.to_netcdf(seasonal_file)
        print(f"✓ Saved {seasonal_file.name}")

    combined_monthly_file = None
    if monthly:
        combined_monthly_file = model_dir / (
            f"cmip6_{file_model}_temperature_anomalies_all_scenarios_"
            f"{baseline_start_year}-{baseline_end_year}baseline.nc"
        )
        _combine_scenarios_to_file(monthly, combined_monthly_file)
        print(f"✓ Saved {combined_monthly_file.name}")

    combined_seasonal_file = None
    if seasonal:
        seasonal_label = "JJA" if months == [6, 7, 8] else "months"
        combined_seasonal_file = model_dir / (
            f"cmip6_{file_model}_temperature_anomalies_{seasonal_label}_all_scenarios_"
            f"{baseline_start_year}-{baseline_end_year}baseline.nc"
        )
        _combine_scenarios_to_file(seasonal, combined_seasonal_file)
        print(f"✓ Saved {combined_seasonal_file.name}")

    return {
        "monthly": monthly,
        "seasonal": seasonal,
        "combined_monthly": combined_monthly_file,
        "combined_seasonal": combined_seasonal_file,
    }


def cleanup_intermediate_files(model_dir, file_model):
    """
    Remove intermediate and redundant files, keeping only original downloaded files 
    and the final scenario-specific anomaly files.
    
    Keeps:
    - cmip6_{variable}_{model}_{experiment}_{years}.nc (original downloads)
    - cmip6_{model}_temperature_anomalies_all_scenarios_*baseline.nc (combined scenario outputs)
    
    Removes:
    - {variable}_Amon_*.nc (raw downloads with CMIP6 naming)
    - cmip6_{variable}_{model}_historical+ssp*_*.nc (intermediate combined timeline files)
    - cmip6_{model}_temperature_anomalies_historical+ssp*_*baseline.nc (per-scenario anomalies)
    - cmip6_{model}_temperature_anomalies_JJA_historical+ssp*_*baseline.nc (per-scenario JJA anomalies)
    - cmip6_{model}_temperature_anomalies_*baseline.nc (old anomaly file without scenario)
    
    Args:
        model_dir: Path to model directory
        file_model: Sanitized model name for filename matching
    """
    import glob
    
    model_dir = Path(model_dir)
    files = list(model_dir.glob("*.nc"))
    
    removed_count = 0
    for f in files:
        fname = f.name
        
        # Remove raw Amon files (duplicates of renamed files)
        if "_Amon_" in fname:
            f.unlink()
            print(f"  Removed: {fname}")
            removed_count += 1
        # Remove intermediate combined timeline files
        elif "historical+ssp" in fname and "temperature_anomalies" not in fname:
            f.unlink()
            print(f"  Removed: {fname}")
            removed_count += 1
        # Remove per-scenario anomaly files when combined files exist
        elif (
            "temperature_anomalies_historical+ssp" in fname
            or "temperature_anomalies_JJA_historical+ssp" in fname
        ):
            f.unlink()
            print(f"  Removed: {fname}")
            removed_count += 1
        # Remove old anomaly file without scenario specification
        elif fname == f"cmip6_{file_model}_temperature_anomalies_1961-1990baseline.nc":
            f.unlink()
            print(f"  Removed: {fname}")
            removed_count += 1
        # Remove old combined files (legacy)
        elif "combined_" in fname and "temperature_anomalies" not in fname:
            f.unlink()
            print(f"  Removed: {fname}")
            removed_count += 1
    
    if removed_count > 0:
        print(f"✓ Cleaned up {removed_count} intermediate file(s)")
    else:
        print("✓ No intermediate files to clean up")


def get_models_from_excel(path, sheet_name):
    """Read model list and variable availability from the Excel sheet."""
    df = pd.read_excel(path, sheet_name=sheet_name)

    required_columns = {"Model", "tasmax", "tasmin"}
    missing = required_columns - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns in Excel sheet: {', '.join(sorted(missing))}")

    models = df["Model"].dropna().astype(str).tolist()
    availability = {
        "tasmax": df.set_index("Model")["tasmax"].to_dict(),
        "tasmin": df.set_index("Model")["tasmin"].to_dict(),
    }

    return models, availability


def download_model_scenario(
    client,
    model,
    experiment,
    variables,
    availability,
    download_dir,
    dataset="projections-cmip6",
    area=None,
    location=None,
):
    """
    Download data for a single model and experiment.
    
    Args:
        area: List [North, West, South, East] bounding box. 
              Defaults to North Carolina [36.6, -84.3, 33.8, -75.4].
        location: Folder name for geographic location (e.g., "NewYork", "NorthCarolina").
                  If provided, downloads are organized as download_dir/location/model/
    """
    if area is None:
        # Default to North Carolina bounds
        area = [36.6, -84.3, 33.8, -75.4]
    
    experiments = {
        "historical": (1850, 2014),
        "ssp126": (2015, 2300),
        "ssp245": (2015, 2300),
        "ssp585": (2015, 2300),
    }

    if experiment not in experiments:
        raise ValueError(f"Unsupported experiment: {experiment}")

    start_year, end_year = experiments[experiment]

    model_clean = model.strip()
    model_id = model_clean.lower().replace("-", "_").replace(" ", "_")
    file_model = model_clean.replace(" ", "_")
    
    # Organize by location then model if location is provided
    if location:
        model_dir = os.path.join(download_dir, location, file_model)
    else:
        model_dir = os.path.join(download_dir, file_model)
    os.makedirs(model_dir, exist_ok=True)

    for variable_key, variable_name in variables.items():
        if availability.get(variable_key, {}).get(model, "").lower() != "available":
            print(f"Skipping {model} {variable_key}: not available in sheet")
            continue

        request = {
            "temporal_resolution": "monthly",
            "experiment": experiment,
            "variable": variable_name,
            "model": model_id,
            "month": ["01", "02", "03", "04", "05", "06",
                      "07", "08", "09", "10", "11", "12"],
            "year": generate_year_range(start_year, end_year),
            # Area format: [North, West, South, East]
            "area": area,
            "format": "netcdf"
        }

        file_name = (
            f"cmip6_{variable_key}_{file_model}_{experiment}_{start_year}-{end_year}.nc"
        )
        file_path = os.path.join(model_dir, file_name)
        
        # Check if file already exists
        if os.path.exists(file_path):
            print(f"✓ File already exists, skipping: {file_name}")
            continue
        
        print(
            "\nDownloading..."
            f"\n  Model: {model_clean}"
            f"\n  Variable: {variable_key}"
            f"\n  Experiment: {experiment}"
            f"\n  Years: {start_year}-{end_year}"
            f"\n  Output: {file_name}"
        )

        result = client.retrieve(dataset, request)
        result.download(file_path)

        print(f"✓ Download complete! File saved as: {file_name}")


def download_cmip6_data(download_dir="CMIP6", area=None, location=None):
    """
    Download CMIP6 historical data for a specified region.
    
    Args:
        download_dir: Directory to save downloads. Defaults to "CMIP6".
        area: Bounding box [North, West, South, East]. 
              Defaults to North Carolina [36.6, -84.3, 33.8, -75.4].
        location: Folder name for geographic location (e.g., "NewYork", "NorthCarolina").
                  If provided, downloads are organized as download_dir/location/model/
    
    Variables:
    - tasmax: Daily maximum near-surface air temperature
    - tasmin: Daily minimum near-surface air temperature
    """
    
    if area is None:
        area = [36.6, -84.3, 33.8, -75.4]
    
    dataset = "projections-cmip6"
    excel_file = "CMIP6_Model_Availability.xlsx"
    sheet_name = "Intersection_All_SSPs"

    variables = {
        "tasmax": "daily_maximum_near_surface_air_temperature",
        "tasmin": "daily_minimum_near_surface_air_temperature",
    }

    models, availability = get_models_from_excel(excel_file, sheet_name)

    os.makedirs(download_dir, exist_ok=True)

    client = cdsapi.Client()

    print("Downloading CMIP6 data...")
    print(f"Dataset: {dataset}")
    print(f"Models from sheet: {sheet_name} ({len(models)} total)")
    print(f"Experiments: historical, ssp126, ssp245, ssp585")
    print(f"Area (N, W, S, E): {area}")
    if location:
        print(f"Location: {location}")

    for model in models:
        for experiment in ["historical", "ssp126", "ssp245", "ssp585"]:
            download_model_scenario(
                client=client,
                model=model,
                experiment=experiment,
                variables=variables,
                availability=availability,
                download_dir=download_dir,
                dataset=dataset,
                area=area,
                location=location,
            )


if __name__ == "__main__":
    try:
        download_cmip6_data()
    except Exception as e:
        print(f"✗ Error: {e}")
        print("\nTroubleshooting:")
        print("- Verify ~/.cdsapirc exists and contains valid API credentials")
        print("- Check that you've accepted the CMIP6 Terms of Use on the CDS website")
        print("- Ensure your API key has access to projections-cmip6 dataset")
