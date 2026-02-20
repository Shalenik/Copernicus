#!/usr/bin/env python3
"""
Investigate CMIP6 processing errors for specific models.

Usage:
  python investigate_model_errors.py --location NewYork --download-dir CMIP6
"""

import argparse
from pathlib import Path

import xarray as xr

from cmip6 import open_dataset_auto


def summarize_time_axis(ds: xr.Dataset, label: str):
    time_var = ds["time"]
    print(f"\n[{label}]")
    print(f"  time dtype: {time_var.dtype}")
    print(f"  time type: {type(time_var.values[0])}")
    cal = time_var.encoding.get("calendar") or time_var.attrs.get("calendar")
    units = time_var.encoding.get("units") or time_var.attrs.get("units")
    print(f"  calendar: {cal}")
    print(f"  units: {units}")
    print(f"  n timesteps: {time_var.size}")
    print(f"  first time: {time_var.values[0]}")
    print(f"  last time:  {time_var.values[-1]}")
    try:
        years = time_var.dt.year
        print(f"  year min/max: {int(years.min())} / {int(years.max())}")
    except Exception as e:
        print(f"  year min/max: ERROR -> {e}")


def inspect_model(model_dir: Path, model_name: str):
    print(f"\n{'='*70}\nInspecting {model_name}\n{'='*70}")

    # Check combined all-scenarios outputs first (if present)
    combined_monthly = model_dir / f"cmip6_{model_name}_temperature_anomalies_all_scenarios_1961-1990baseline.nc"
    combined_jja = model_dir / f"cmip6_{model_name}_temperature_anomalies_JJA_all_scenarios_1961-1990baseline.nc"

    for path in [combined_monthly, combined_jja]:
        if path.exists():
            ds = open_dataset_auto(path, download_dir=model_dir)
            summarize_time_axis(ds, f"combined: {path.name}")
        else:
            print(f"  missing: {path.name}")

    # Inspect raw historical/ssp files for tasmax/tasmin
    for var in ["tasmax", "tasmin"]:
        for exp in ["historical", "ssp126", "ssp245", "ssp585"]:
            f = next(model_dir.glob(f"cmip6_{var}_{model_name}_{exp}_*.nc"), None)
            if f is None:
                print(f"  missing: cmip6_{var}_{model_name}_{exp}_*.nc")
                continue
            ds = open_dataset_auto(f, download_dir=model_dir)
            summarize_time_axis(ds, f"raw: {f.name}")


def main():
    parser = argparse.ArgumentParser(description="Investigate CMIP6 model time/calendar issues")
    parser.add_argument("--location", default="NewYork")
    parser.add_argument("--download-dir", default="CMIP6")
    args = parser.parse_args()

    base_dir = Path(args.download_dir) / args.location
    if not base_dir.exists():
        raise SystemExit(f"Location directory not found: {base_dir}")

    # Models with reported errors
    for model in ["IPSL-CM6A-LR", "MRI-ESM2-0"]:
        model_dir = base_dir / model
        if not model_dir.exists():
            print(f"\nMissing model directory: {model_dir}")
            continue
        inspect_model(model_dir, model)


if __name__ == "__main__":
    main()
