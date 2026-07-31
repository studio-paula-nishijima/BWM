import pandas as pd

def load_lamah_column(csv_path, column, chunksize=50000):

    for chunk in pd.read_csv(
        csv_path,
        sep=";",
        chunksize=chunksize
    ):

        print("AVAILABLE COLUMNS:")
        print(chunk.columns)

        if column in chunk:
            yield chunk[column].dropna().values
