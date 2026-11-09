import os

# numpy's math library (OpenBLAS) reserves a work buffer per CPU thread when it loads: about 480 MB
# on a 16-thread PC. We never do the matrix math it's for, so one thread is plenty. This has to run
# before anything imports numpy, which is why it's here.
for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")
