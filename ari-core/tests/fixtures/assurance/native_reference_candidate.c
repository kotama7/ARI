#include <math.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#ifdef ARI_NEGATIVE_CONTROL
#define ARI_CORRUPT(value) ((value) + 1.0)
#else
#define ARI_CORRUPT(value) (value)
#endif

static int ari_isolation_probe(void) {
#ifdef ARI_PROBE_ORACLE_ACCESS
  int oracle_descriptor =
      open("/opt/ari-core/ari/assurance/native_hpc_gemm.py", O_RDONLY);
  if (oracle_descriptor >= 0) {
    close(oracle_descriptor);
    return 77;
  }
  int descriptor = open(
      "/ari/inputs/ari-candidate-write-probe", O_WRONLY | O_CREAT | O_TRUNC,
      0600);
  if (descriptor >= 0) {
    close(descriptor);
    unlink("/ari/inputs/ari-candidate-write-probe");
    return 78;
  }
#endif
  return 0;
}

#define DEFINE_GEMM(TYPE, SUFFIX)                                                \
  int ari_gemm_##SUFFIX(                                                        \
      int m, int n, int k, int transpose_a, int transpose_b, int lda, int ldb, \
      int ldc, TYPE alpha, const TYPE *a, const TYPE *b, TYPE beta, TYPE *c,    \
      int thread_count) {                                                       \
    (void)thread_count;                                                         \
    if (ari_isolation_probe() != 0) {                                            \
      return ari_isolation_probe();                                              \
    }                                                                           \
    if (m < 0 || n < 0 || k < 0 || lda < (transpose_a ? m : k) ||             \
        ldb < (transpose_b ? k : n) || ldc < n || !a || !b || !c) {            \
      return 1;                                                                 \
    }                                                                           \
    for (int i = 0; i < m; ++i) {                                               \
      for (int j = 0; j < n; ++j) {                                             \
        TYPE sum = 0;                                                           \
        for (int p = 0; p < k; ++p) {                                           \
          TYPE av = a[transpose_a ? p * lda + i : i * lda + p];                \
          TYPE bv = b[transpose_b ? j * ldb + p : p * ldb + j];                \
          sum += av * bv;                                                       \
        }                                                                       \
        TYPE value = alpha * sum + beta * c[i * ldc + j];                       \
        c[i * ldc + j] = (TYPE)ARI_CORRUPT(value);                              \
      }                                                                         \
    }                                                                           \
    return 0;                                                                   \
  }

DEFINE_GEMM(float, f32)
DEFINE_GEMM(double, f64)

#define DEFINE_SPMM(TYPE, SUFFIX)                                                \
  int ari_spmm_##SUFFIX(                                                        \
      int m, int k, int n, int64_t nnz, const int64_t *row_ptr,                \
      const int64_t *col_idx, const TYPE *values, const TYPE *b, int ldb,      \
      TYPE *c, int ldc, TYPE alpha, TYPE beta, int thread_count,               \
      unsigned int flags) {                                                     \
    (void)thread_count;                                                         \
    (void)flags;                                                                \
    if (ari_isolation_probe() != 0) {                                            \
      return ari_isolation_probe();                                              \
    }                                                                           \
    if (m < 0 || k < 0 || n < 0 || nnz < 0 || !row_ptr || !col_idx ||         \
        !values || !b || !c || ldb < n || ldc < n || row_ptr[0] != 0 ||       \
        row_ptr[m] != nnz) {                                                    \
      return 1;                                                                 \
    }                                                                           \
    for (int row = 0; row < m; ++row) {                                         \
      if (row_ptr[row] > row_ptr[row + 1] || row_ptr[row] < 0 ||               \
          row_ptr[row + 1] > nnz) {                                             \
        return 1;                                                               \
      }                                                                         \
      for (int64_t pos = row_ptr[row]; pos < row_ptr[row + 1]; ++pos) {        \
        if (col_idx[pos] < 0 || col_idx[pos] >= k) {                            \
          return 1;                                                             \
        }                                                                       \
      }                                                                         \
    }                                                                           \
    for (int row = 0; row < m; ++row) {                                         \
      for (int rhs = 0; rhs < n; ++rhs) {                                       \
        TYPE sum = 0;                                                           \
        for (int64_t pos = row_ptr[row]; pos < row_ptr[row + 1]; ++pos) {      \
          sum += values[pos] * b[col_idx[pos] * ldb + rhs];                    \
        }                                                                       \
        TYPE value = alpha * sum + beta * c[row * ldc + rhs];                  \
        c[row * ldc + rhs] = (TYPE)ARI_CORRUPT(value);                         \
      }                                                                         \
    }                                                                           \
    return 0;                                                                   \
  }

DEFINE_SPMM(float, f32)
DEFINE_SPMM(double, f64)

static size_t ari_index(int x, int y, int z, int nx, int ny) {
  return ((size_t)z * (size_t)ny + (size_t)y) * (size_t)nx + (size_t)x;
}

#define DEFINE_STENCIL(TYPE, SUFFIX)                                             \
  int ari_stencil_##SUFFIX(                                                     \
      int nx, int ny, int nz, int iterations, int periodic, int in_place,      \
      const TYPE *input, TYPE *output, int thread_count) {                      \
    (void)in_place;                                                             \
    (void)thread_count;                                                         \
    if (ari_isolation_probe() != 0) {                                            \
      return ari_isolation_probe();                                              \
    }                                                                           \
    if (nx <= 0 || ny <= 0 || nz <= 0 || iterations < 0 || !input ||          \
        !output) {                                                              \
      return 1;                                                                 \
    }                                                                           \
    size_t count = (size_t)nx * (size_t)ny * (size_t)nz;                       \
    if (count > SIZE_MAX / sizeof(TYPE)) {                                      \
      return 1;                                                                 \
    }                                                                           \
    TYPE *current = (TYPE *)malloc(count * sizeof(TYPE));                       \
    TYPE *following = (TYPE *)malloc(count * sizeof(TYPE));                     \
    if (!current || !following) {                                               \
      free(current);                                                            \
      free(following);                                                          \
      return 1;                                                                 \
    }                                                                           \
    memcpy(current, input, count * sizeof(TYPE));                               \
    for (int iteration = 0; iteration < iterations; ++iteration) {             \
      memcpy(following, current, count * sizeof(TYPE));                         \
      for (int z = 0; z < nz; ++z) {                                            \
        for (int y = 0; y < ny; ++y) {                                          \
          for (int x = 0; x < nx; ++x) {                                        \
            int edge = x == 0 || x == nx - 1 || y == 0 || y == ny - 1 ||      \
                       z == 0 || z == nz - 1;                                   \
            if (!periodic && edge) {                                            \
              continue;                                                         \
            }                                                                   \
            TYPE sum = current[ari_index(x, y, z, nx, ny)];                     \
            int neighbours = 0;                                                 \
            const int delta[6][3] = {                                           \
                {-1, 0, 0}, {1, 0, 0}, {0, -1, 0},                             \
                {0, 1, 0},  {0, 0, -1}, {0, 0, 1}};                            \
            for (int d = 0; d < 6; ++d) {                                      \
              int xx = x + delta[d][0];                                         \
              int yy = y + delta[d][1];                                         \
              int zz = z + delta[d][2];                                         \
              if (periodic) {                                                   \
                xx = (xx + nx) % nx;                                            \
                yy = (yy + ny) % ny;                                            \
                zz = (zz + nz) % nz;                                            \
              } else if (xx < 0 || xx >= nx || yy < 0 || yy >= ny ||          \
                         zz < 0 || zz >= nz) {                                  \
                continue;                                                       \
              }                                                                 \
              sum += current[ari_index(xx, yy, zz, nx, ny)];                   \
              ++neighbours;                                                     \
            }                                                                   \
            following[ari_index(x, y, z, nx, ny)] =                            \
                sum / (TYPE)(1 + neighbours);                                   \
          }                                                                     \
        }                                                                       \
      }                                                                         \
      TYPE *swap = current;                                                     \
      current = following;                                                      \
      following = swap;                                                         \
    }                                                                           \
    memcpy(output, current, count * sizeof(TYPE));                              \
    if (count > 0) {                                                            \
      output[0] = (TYPE)ARI_CORRUPT(output[0]);                                 \
    }                                                                           \
    free(current);                                                              \
    free(following);                                                            \
    return 0;                                                                   \
  }

DEFINE_STENCIL(float, f32)
DEFINE_STENCIL(double, f64)
