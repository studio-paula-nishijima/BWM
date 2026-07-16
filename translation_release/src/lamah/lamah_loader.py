import pandas as pd


def build_timestamps(chunk, date_columns):

    year = chunk[date_columns["year"]]

    month = chunk[date_columns["month"]]

    day = chunk[date_columns["day"]]

    hour = (
        chunk[date_columns["hour"]]
        if "hour" in date_columns
        else 0
    )

    minute = (
        chunk[date_columns["minute"]]
        if "minute" in date_columns
        else 0
    )

    timestamps = pd.to_datetime({
        "year": year,
        "month": month,
        "day": day,
        "hour": hour,
        "minute": minute
    })

    return timestamps.values


def load_lamah_column(
    csv_path,
    column,
    date_columns,
    chunksize=50000
):

    for chunk in pd.read_csv(
        csv_path,
        sep=";",
        chunksize=chunksize
    ):

        timestamps = build_timestamps(
            chunk,
            date_columns
        )

        values = chunk[column].values

        yield timestamps, values
