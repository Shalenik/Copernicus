#!/usr/bin/env python3
"""
Bulk download CMIP6 data for all models and create validation reports.

This script downloads tasmax and tasmin for all models in the Excel sheet,
computes anomalies, and generates plots and summary statistics.

Usage:
    python download_all_models.py --location NewYork --area "45 -80 40 -75"
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime

import pandas as pd
import xarray as xr
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np

from cmip6 import (
    download_model_scenario,
    get_models_from_excel,
    open_dataset_auto,
    combine_historical_with_scenarios,
    compute_anomalies,
    compute_seasonal_anomalies,
    average_tasmax_tasmin,
    cleanup_intermediate_files,
)
import cdsapi


def download_all_models(
    location, area, download_dir="CMIP6", excel_file="CMIP6_Model_Availability.xlsx"
):
    """Download tasmax and tasmin for all models."""
    
    sheet_name = "Intersection_All_SSPs"
    models, availability = get_models_from_excel(excel_file, sheet_name)
    
    variables = {
        "tasmax": "daily_maximum_near_surface_air_temperature",
        "tasmin": "daily_minimum_near_surface_air_temperature",
    }
    
    experiment_years = {
        "historical": (1850, 2014),
        "ssp126": (2015, 2300),
        "ssp245": (2015, 2300),
        "ssp585": (2015, 2300),
    }
    
    client = cdsapi.Client()
    
    print(f"\n{'='*70}")
    print(f"BULK DOWNLOAD: {location}")
    print(f"{'='*70}")
    print(f"Area (N, W, S, E): {area}")
    print(f"Models to download: {len(models)}")
    print(f"Variables: tasmax, tasmin")
    print(f"Experiments: historical, ssp126, ssp245, ssp585")
    print(f"{'='*70}\n")
    
    download_dir = Path(download_dir)
    location_dir = download_dir / location
    
    for i, model in enumerate(models, 1):
        print(f"\n[{i}/{len(models)}] Downloading {model}...")
        
        for variable in variables.keys():
            for experiment in ["historical", "ssp126", "ssp245", "ssp585"]:
                try:
                    download_model_scenario(
                        client=client,
                        model=model,
                        experiment=experiment,
                        variables={variable: variables[variable]},
                        availability=availability,
                        download_dir=str(download_dir),
                        area=area,
                        location=location,
                    )
                except Exception as e:
                    print(f"  ✗ Error downloading {model} {variable} {experiment}: {e}")
    
    print(f"\n{'='*70}")
    print("✓ All downloads complete!")
    print(f"{'='*70}\n")
    
    return location_dir, models


def process_all_models(location_dir, models):
    """
    Process all downloaded models: combine scenarios, compute anomalies, clean up.
    
    Returns dictionary with model info and time ranges.
    """
    
    experiment_years = {
        "historical": (1850, 2014),
        "ssp126": (2015, 2300),
        "ssp245": (2015, 2300),
        "ssp585": (2015, 2300),
    }
    
    scenarios = ["ssp126", "ssp245", "ssp585"]
    
    model_info = {}
    
    print(f"\n{'='*70}")
    print("PROCESSING AND COMPUTING ANOMALIES")
    print(f"{'='*70}\n")
    
    for i, model in enumerate(models, 1):
        model_clean = model.strip().replace(" ", "_")
        model_dir = location_dir / model_clean
        
        if not model_dir.exists():
            print(f"[{i}/{len(models)}] {model}: ✗ Directory not found, skipping")
            continue
        
        print(f"[{i}/{len(models)}] Processing {model}...")
        
        model_info[model] = {"status": "pending"}
        
        try:
            # Combine historical with each scenario for tasmax
            print(f"  - Combining tasmax with scenarios...", end=" ")
            combine_historical_with_scenarios(model_dir, "tasmax", model_clean, experiment_years)
            print("✓")
            
            # Combine historical with each scenario for tasmin
            print(f"  - Combining tasmin with scenarios...", end=" ")
            combine_historical_with_scenarios(model_dir, "tasmin", model_clean, experiment_years)
            print("✓")
            
            # Process each scenario
            print(f"  - Processing scenarios:")
            scenario_datasets = {}
            scenario_jja_datasets = {}
            
            for scenario in scenarios:
                # Load scenario files
                tasmax_file = model_dir / f"cmip6_tasmax_{model_clean}_historical+{scenario}_1850-2300.nc"
                tasmin_file = model_dir / f"cmip6_tasmin_{model_clean}_historical+{scenario}_1850-2300.nc"
                
                if not tasmax_file.exists() or not tasmin_file.exists():
                    print(f"    {scenario}: Missing files, skipping")
                    continue
                
                # Load datasets
                ds_tasmax = open_dataset_auto(tasmax_file, download_dir=model_dir)
                ds_tasmin = open_dataset_auto(tasmin_file, download_dir=model_dir)
                
                # Compute anomalies
                ds_tasmax_anom = compute_anomalies(ds_tasmax, baseline_start_year=1961, baseline_end_year=1990)
                ds_tasmin_anom = compute_anomalies(ds_tasmin, baseline_start_year=1961, baseline_end_year=1990)
                
                # Average tasmax and tasmin
                ds_avg_anom = average_tasmax_tasmin(ds_tasmax_anom, ds_tasmin_anom)
                
                # Store for later
                scenario_datasets[scenario] = ds_avg_anom
                
                # Save scenario-specific anomaly file
                output_file = model_dir / f"cmip6_{model_clean}_temperature_anomalies_historical+{scenario}_1961-1990baseline.nc"
                ds_avg_anom.to_netcdf(output_file)
                
                # Compute JJA anomalies from raw averages
                ds_avg_raw = average_tasmax_tasmin(ds_tasmax, ds_tasmin)
                ds_avg_jja_anom = compute_seasonal_anomalies(
                    ds_avg_raw,
                    months=[6, 7, 8],
                    baseline_start_year=1961,
                    baseline_end_year=1990,
                )
                scenario_jja_datasets[scenario] = ds_avg_jja_anom
                jja_output_file = model_dir / (
                    f"cmip6_{model_clean}_temperature_anomalies_JJA_historical+{scenario}_1961-1990baseline.nc"
                )
                ds_avg_jja_anom.to_netcdf(jja_output_file)
                print(f"    {scenario}: ✓ (monthly + JJA)")
            
            if not scenario_datasets:
                raise ValueError("No scenarios successfully processed")

            # Save combined all-scenarios monthly and JJA anomaly files
            scenarios_order = [s for s in scenarios if s in scenario_datasets]
            combined_monthly = xr.concat(
                [scenario_datasets[s] for s in scenarios_order], dim="scenario"
            ).assign_coords(scenario=scenarios_order)
            combined_monthly_file = model_dir / (
                f"cmip6_{model_clean}_temperature_anomalies_all_scenarios_1961-1990baseline.nc"
            )
            combined_monthly.to_netcdf(combined_monthly_file)
            print(f"  - Saved {combined_monthly_file.name}")

            scenarios_order_jja = [s for s in scenarios if s in scenario_jja_datasets]
            combined_jja = xr.concat(
                [scenario_jja_datasets[s] for s in scenarios_order_jja], dim="scenario"
            ).assign_coords(scenario=scenarios_order_jja)
            combined_jja_file = model_dir / (
                f"cmip6_{model_clean}_temperature_anomalies_JJA_all_scenarios_1961-1990baseline.nc"
            )
            combined_jja.to_netcdf(combined_jja_file)
            print(f"  - Saved {combined_jja_file.name}")
            
            # Use first scenario for time range info (cftime-safe)
            first_ds = list(scenario_datasets.values())[0]
            time_var = first_ds["time"]
            year_vals = time_var.dt.year
            time_min_year = int(year_vals.min().values)
            time_max_year = int(year_vals.max().values)
            n_timesteps = time_var.size
            
            model_info[model] = {
                "status": "success",
                "time_min": time_min_year,
                "time_max": time_max_year,
                "timesteps": n_timesteps,
                "scenarios": list(scenario_datasets.keys()),
            }
            
            # Cleanup
            print(f"  - Cleaning up intermediate files...", end=" ")
            cleanup_intermediate_files(model_dir, model_clean)
            print("✓")
            
        except Exception as e:
            print(f"  ✗ Error: {e}")
            model_info[model]["status"] = f"error: {str(e)}"
    
    print(f"\n{'='*70}\n")
    
    return model_info


def create_summary_report(model_info, location_dir, output_csv=None):
    """Create summary CSV and return as DataFrame."""
    
    if output_csv is None:
        output_csv = location_dir.parent / f"{location_dir.name}_summary.csv"
    
    rows = []
    for model, info in model_info.items():
        row = {
            "Model": model,
            "Status": info.get("status", "unknown"),
            "Time Min": info.get("time_min", ""),
            "Time Max": info.get("time_max", ""),
            "Timesteps": info.get("timesteps", ""),
        }
        rows.append(row)
    
    df = pd.DataFrame(rows)
    df.to_csv(output_csv, index=False)
    
    print(f"✓ Summary saved to: {output_csv}\n")
    
    return df


def combine_all_models_outputs(
    location_dir,
    models,
    baseline_start=1961,
    baseline_end=1990,
    min_year=None,
    max_year=None,
):
    """Combine per-model anomaly outputs into single files for the location."""
    def _normalize_monthly_time(ds: xr.Dataset) -> xr.Dataset:
        time_da = ds["time"]
        years = time_da.dt.year
        months = time_da.dt.month
        month_index = (years * 12 + (months - 1)).astype("int64")
        ds = ds.assign_coords(time=month_index)
        ds["time"].attrs["description"] = "month_index = year*12 + (month-1)"
        return ds

    combined_monthly = []
    combined_jja = []
    model_labels_monthly = []
    model_labels_jja = []

    for model in models:
        model_clean = model.strip().replace(" ", "_")
        model_dir = location_dir / model_clean

        monthly_file = model_dir / (
            f"cmip6_{model_clean}_temperature_anomalies_all_scenarios_{baseline_start}-{baseline_end}baseline.nc"
        )
        jja_file = model_dir / (
            f"cmip6_{model_clean}_temperature_anomalies_JJA_all_scenarios_{baseline_start}-{baseline_end}baseline.nc"
        )

        if monthly_file.exists():
            ds_monthly = open_dataset_auto(monthly_file, download_dir=model_dir)
            if min_year is not None or max_year is not None:
                years = ds_monthly["time"].dt.year
                if min_year is None:
                    min_year = int(years.min().values)
                if max_year is None:
                    max_year = int(years.max().values)
                ds_monthly = ds_monthly.where(
                    (years >= min_year) & (years <= max_year), drop=True
                )
            ds_monthly = _normalize_monthly_time(ds_monthly)
            combined_monthly.append(ds_monthly)
            model_labels_monthly.append(model)

        if jja_file.exists():
            ds_jja = open_dataset_auto(jja_file, download_dir=model_dir)
            if min_year is not None or max_year is not None:
                years = ds_jja["year"]
                if min_year is None:
                    min_year = int(years.min().values)
                if max_year is None:
                    max_year = int(years.max().values)
                ds_jja = ds_jja.where(
                    (years >= min_year) & (years <= max_year), drop=True
                )
            combined_jja.append(ds_jja)
            model_labels_jja.append(model)

    outputs = {}

    if combined_monthly:
        combined_monthly_ds = xr.concat(combined_monthly, dim="model").assign_coords(
            model=model_labels_monthly
        )
        out_monthly = location_dir / (
            f"{location_dir.name}_temperature_anomalies_all_models_{baseline_start}-{baseline_end}baseline.nc"
        )
        combined_monthly_ds.to_netcdf(out_monthly)
        outputs["monthly"] = out_monthly

    if combined_jja:
        combined_jja_ds = xr.concat(combined_jja, dim="model").assign_coords(
            model=model_labels_jja
        )
        out_jja = location_dir / (
            f"{location_dir.name}_temperature_anomalies_JJA_all_models_{baseline_start}-{baseline_end}baseline.nc"
        )
        combined_jja_ds.to_netcdf(out_jja)
        outputs["jja"] = out_jja

    return outputs


def plot_all_models_grid(model_info, location_dir, output_png=None, variable="avg"):
    """
    Create a grid of plots for all models (one subplot per model).
    Plots historical in black and SSP scenarios in color-coded lines.
    
    Args:
        variable: "avg" only (temperature anomalies)
    """
    
    successful_models = [m for m, info in model_info.items() if info["status"] == "success"]
    
    if not successful_models:
        print("No successful models to plot")
        return
    
    if output_png is None:
        output_png = location_dir.parent / f"{location_dir.name}_plots_{variable}.png"
    
    n_models = len(successful_models)
    ncols = 3
    nrows = (n_models + ncols - 1) // ncols
    
    fig = plt.figure(figsize=(18, 5 * nrows))
    gs = gridspec.GridSpec(nrows, ncols, figure=fig, hspace=0.3, wspace=0.3)
    
    print(f"Creating {variable} plots for {n_models} models ({nrows}x{ncols} grid)...")
    
    color_map = {
        "ssp126": "green",
        "ssp245": "orange",
        "ssp585": "red",
    }
    
    scenarios = ["ssp126", "ssp245", "ssp585"]

    def _to_decimal_year(time_da):
        """Convert time coordinate to decimal year for plotting (cftime-safe)."""
        years = time_da.dt.year
        months = time_da.dt.month if "month" in dir(time_da.dt) else None
        if months is None:
            return years.astype(float)
        return years.astype(float) + (months.astype(float) - 1) / 12.0

    def _plot_series(ax, time_da, values, label, color, linewidth=1.5):
        x = _to_decimal_year(time_da).values
        ax.plot(x, values, label=label, color=color, linewidth=linewidth)
    
    for idx, model in enumerate(successful_models):
        row = idx // ncols
        col = idx % ncols
        ax = fig.add_subplot(gs[row, col])
        
        model_clean = model.strip().replace(" ", "_")
        model_dir = location_dir / model_clean
        
        try:
            historical_plotted = False
            plotted_any = False

            combined_file = model_dir / (
                f"cmip6_{model_clean}_temperature_anomalies_all_scenarios_1961-1990baseline.nc"
            )

            if combined_file.exists():
                ds = open_dataset_auto(combined_file, download_dir=model_dir)
                var_name = "temperature" if "temperature" in ds.data_vars else list(ds.data_vars)[0]
                da = ds[var_name]

                if "scenario" in da.dims:
                    scenarios_in_file = list(da["scenario"].values)
                    for scenario in scenarios_in_file:
                        da_s = da.sel(scenario=scenario)
                        spatial_dims = [d for d in da_s.dims if d != "time"]
                        series = da_s.mean(dim=spatial_dims) if spatial_dims else da_s
                        years = series["time"].dt.year
                        historical = series.where(years < 2015, drop=True)
                        ssp = series.where(years >= 2015, drop=True)

                        if not historical_plotted and len(historical) > 0:
                            _plot_series(ax, historical["time"], historical.values, "historical", "black")
                            historical_plotted = True
                            plotted_any = True
                        elif len(historical) > 0:
                            _plot_series(ax, historical["time"], historical.values, None, "black")
                            plotted_any = True

                        if len(ssp) > 0:
                            _plot_series(
                                ax,
                                ssp["time"],
                                ssp.values,
                                str(scenario),
                                color_map.get(str(scenario), "gray"),
                            )
                            plotted_any = True
                else:
                    # Fallback if scenario dim missing
                    spatial_dims = [d for d in da.dims if d != "time"]
                    series = da.mean(dim=spatial_dims) if spatial_dims else da
                    _plot_series(ax, series["time"], series.values, "combined", "black")
                    plotted_any = True
            else:
                # Fallback to per-scenario files if combined file not present
                for scenario in scenarios:
                    file_path = model_dir / (
                        f"cmip6_{model_clean}_temperature_anomalies_historical+{scenario}_1961-1990baseline.nc"
                    )
                    if not file_path.exists():
                        continue

                    ds = open_dataset_auto(file_path, download_dir=model_dir)
                    var_name = "temperature" if "temperature" in ds.data_vars else list(ds.data_vars)[0]
                    da = ds[var_name]
                    spatial_dims = [d for d in da.dims if d != "time"]
                    series = da.mean(dim=spatial_dims) if spatial_dims else da
                    years = series["time"].dt.year
                    historical = series.where(years < 2015, drop=True)
                    ssp = series.where(years >= 2015, drop=True)

                    if not historical_plotted and len(historical) > 0:
                        _plot_series(ax, historical["time"], historical.values, "historical", "black")
                        historical_plotted = True
                        plotted_any = True
                    elif len(historical) > 0:
                        _plot_series(ax, historical["time"], historical.values, None, "black")
                        plotted_any = True

                    if len(ssp) > 0:
                        _plot_series(
                            ax,
                            ssp["time"],
                            ssp.values,
                            scenario,
                            color_map.get(scenario, "gray"),
                        )
                        plotted_any = True

            ax.set_title(f"{model}", fontsize=11, fontweight="bold")
            ax.set_xlabel("Year", fontsize=9)
            ax.set_ylabel("Anomaly (K)", fontsize=9)
            ax.grid(True, alpha=0.3)
            ax.axhline(y=0, color='gray', linestyle='--', linewidth=0.5, alpha=0.5)
            if idx == 0 and plotted_any:
                ax.legend(loc="best", fontsize=8)
            
        except Exception as e:
            ax.text(0.5, 0.5, f"{model}\n(Error: {str(e)[:30]})", 
                   ha="center", va="center", transform=ax.transAxes, fontsize=9)
            ax.set_title(f"{model}", fontsize=11, fontweight="bold")
    
    # Hide empty subplots
    for idx in range(len(successful_models), nrows * ncols):
        row = idx // ncols
        col = idx % ncols
        ax = fig.add_subplot(gs[row, col])
        ax.axis("off")
    
    var_title = variable.upper()
    fig.suptitle(f"CMIP6 {var_title} Anomalies (1961-1990 Baseline)", 
                fontsize=16, fontweight="bold", y=0.995)
    
    plt.savefig(output_png, dpi=100, bbox_inches="tight")
    print(f"✓ Plot saved to: {output_png}\n")
    plt.close()


def build_model_info_from_summary(summary_csv: Path):
    """Build a minimal model_info dict from summary CSV."""
    df = pd.read_csv(summary_csv)
    model_info = {}
    for _, row in df.iterrows():
        model = str(row.get("Model", "")).strip()
        if not model:
            continue
        model_info[model] = {
            "status": row.get("Status", "unknown"),
            "time_min": row.get("Time Min", ""),
            "time_max": row.get("Time Max", ""),
            "timesteps": row.get("Timesteps", ""),
        }
    return model_info


def main():
    parser = argparse.ArgumentParser(
        description="Bulk download and process CMIP6 models"
    )
    parser.add_argument(
        "--location",
        required=True,
        help="Location name (e.g., NewYork, NorthCarolina)",
    )
    parser.add_argument(
        "--area",
        type=float,
        nargs=4,
        required=True,
        metavar=("N", "W", "S", "E"),
        help="Bounding box: North West South East",
    )
    parser.add_argument(
        "--download-dir",
        default="CMIP6",
        help="Download directory (default: CMIP6)",
    )
    parser.add_argument(
        "--excel-file",
        default="CMIP6_Model_Availability.xlsx",
        help="Excel file with model availability",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip download, only process existing files",
    )
    parser.add_argument(
        "--download-only",
        action="store_true",
        help="Only download, skip processing",
    )
    parser.add_argument(
        "--process-only",
        action="store_true",
        help="Only process existing downloads, skip downloading",
    )
    parser.add_argument(
        "--plot-only",
        action="store_true",
        help="Only generate plots from existing summary and outputs",
    )
    parser.add_argument(
        "--combine-only",
        action="store_true",
        help="Only combine per-model outputs into location-wide files",
    )
    parser.add_argument(
        "--min-year",
        type=int,
        default=None,
        help="Minimum year to include when combining (optional)",
    )
    parser.add_argument(
        "--max-year",
        type=int,
        default=None,
        help="Maximum year to include when combining (optional)",
    )
    
    args = parser.parse_args()
    
    # Validate mutually exclusive options
    if args.skip_download and args.process_only:
        print("Error: --skip-download and --process-only are the same. Use --process-only.")
        sys.exit(1)
    if args.download_only and args.process_only:
        print("Error: --download-only and --process-only are mutually exclusive.")
        sys.exit(1)
    if args.plot_only and (args.download_only or args.process_only or args.skip_download or args.combine_only):
        print("Error: --plot-only cannot be combined with download/process flags.")
        sys.exit(1)
    if args.combine_only and (args.download_only or args.process_only or args.skip_download):
        print("Error: --combine-only cannot be combined with download/process flags.")
        sys.exit(1)
    
    # Handle deprecated --skip-download
    if args.skip_download:
        args.process_only = True
    
    print("\n" + "="*70)
    print("CMIP6 BULK DOWNLOAD AND PROCESSING")
    print("="*70)
    print(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Location: {args.location}")
    print(f"Area: {args.area}")
    if args.download_only:
        print("Mode: DOWNLOAD ONLY")
    elif args.process_only:
        print("Mode: PROCESS ONLY")
    else:
        print("Mode: DOWNLOAD AND PROCESS")
    print("="*70 + "\n")
    
    download_dir = Path(args.download_dir)
    location_dir = download_dir / args.location
    
    if args.plot_only:
        summary_csv = Path(args.download_dir) / f"{args.location}_summary.csv"
        if not summary_csv.exists():
            print(f"Summary CSV not found: {summary_csv}")
            sys.exit(1)
        model_info = build_model_info_from_summary(summary_csv)
        plot_all_models_grid(model_info, location_dir, variable="avg")
        print("Plot-only complete.")
        return

    if args.combine_only:
        summary_csv = Path(args.download_dir) / f"{args.location}_summary.csv"
        if not summary_csv.exists():
            print(f"Summary CSV not found: {summary_csv}")
            sys.exit(1)
        df_summary = pd.read_csv(summary_csv)
        models = df_summary["Model"].dropna().astype(str).tolist()
        combined_outputs = combine_all_models_outputs(
            location_dir,
            models,
            min_year=args.min_year,
            max_year=args.max_year,
        )
        if combined_outputs:
            for key, path in combined_outputs.items():
                print(f"✓ Combined {key} file saved: {path}")
        print("Combine-only complete.")
        return

    if not args.process_only:
        # Download phase
        location_dir, models = download_all_models(
            location=args.location,
            area=args.area,
            download_dir=str(download_dir),
            excel_file=args.excel_file,
        )
    else:
        # Process-only: load models from Excel
        models, _ = get_models_from_excel(args.excel_file, "Intersection_All_SSPs")
    
    if not args.download_only:
        # Process phase
        model_info = process_all_models(location_dir, models)
        
        df_summary = create_summary_report(model_info, location_dir)
        print(df_summary)

        combined_outputs = combine_all_models_outputs(location_dir, models)
        if combined_outputs:
            for key, path in combined_outputs.items():
                print(f"✓ Combined {key} file saved: {path}")
    else:
        print(f"\n{'='*70}")
        print("Skipping processing (--download-only flag set)")
        print(f"{'='*70}\n")
    
    print("="*70)
    print(f"Complete! End time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70 + "\n")


if __name__ == "__main__":
    main()
