"""Packaged executable entry for every desktop platform."""
from app.launcher import main

if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    main()
