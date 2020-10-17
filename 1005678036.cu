#include <sys/time.h>
#include <cuda.h>
#include <stdio.h>


#define HANDLE_ERROR( err ) ( HandleError( err, __FILE__, __LINE__ ) )

static void HandleError( cudaError_t err, const char *file, int line )
{
    if (err != cudaSuccess)
      {
        printf( "Error: %s in %s at line %d\n", cudaGetErrorString( err ),
                file, line );
        exit( EXIT_FAILURE );
    }
}


// time stamp function in seconds
double getTimeStamp() {
	struct timeval tv ;
	gettimeofday( &tv, NULL ) ;
	return (double) tv.tv_usec/1000000 + tv.tv_sec ;
}

// host side matrix addition
void h_addmat(float *A, float *B, float *C, int nx, int ny){

	for (int i =0;i<nx;i++){
		for(int j=0;j<ny;j++){
			C[i*ny+j] = A[i*ny+j]+B[i*ny+j]; 
		}

	}
	return;
}

// device-side matrix addition
__global__ void f_addmat( float *A, float *B, float *C, int nx, int ny ){
	
	int ix = threadIdx.x + blockIdx.x*(blockDim.x) ;
	int iy = threadIdx.y + blockIdx.y*(blockDim.y) ;
	//printf("In add\n");
		
	if( (ix<nx/2) && (iy<ny/2) ){
		int idx = (iy*nx/2 + ix)*4;
		C[idx] = A[idx] + B[idx] ;
		C[idx+1] = A[idx+1] + B[idx+1] ;
		C[idx+2] = A[idx+2] + B[idx+2] ;
		C[idx+3] = A[idx+3] + B[idx+3] ;
		//printf("Thread %d %d\n",ix,iy);
	}
}

void initData(float *M, int x, int y, int flag ){ 
	
	if(flag)
	{	
		//printf("A\n");
		for (int i=0;i<x;i++){
		        for (int j=0;j<y;j++){
			    M[i*y+j] = (float)(i+j)/3.0;
		        }
		}
	}
	else
	{
		//printf("B\n");
		for (int i=0;i<x;i++){
			for (int j=0;j<y;j++){
				M[i*y+j] = (float)3.14*(i+j) ;
			}
		}
	
	}
}

int main( int argc, char *argv[] ) {
	
	
	if (argc!=3){
		printf("Error: Invalid number of arguments.\n");
		exit(1);
	}
	
	int nx = atoi( argv[1] ) ; // should check validity
	int ny = atoi( argv[2] ) ; // should check validity
	
	if(nx <=0 || ny <=0){
		printf("Error: Dimension lessThanOrEqualto Zero.\n");
                exit(1);
	}
	
	if(ny>nx)
	{
		nx=nx^ny;
		ny=nx^ny;
		nx=nx^ny;
	}

	int noElems = (nx)*(ny) ;
	int bytes = noElems * sizeof(float) ;

        // GPU and CPU memory Allocations
        
        float *d_A, *d_B, *d_C ;
        HANDLE_ERROR(cudaMalloc( (float **) &d_A, bytes )) ;
        HANDLE_ERROR(cudaMalloc( (float **) &d_B, bytes )) ;
        HANDLE_ERROR(cudaMalloc( (float **) &d_C, bytes )) ;
	float *h_hC = (float *) malloc( bytes ) ; // host result

        float *h_Ap, *h_Bp, *h_dCp;
        HANDLE_ERROR(cudaMallocHost( (float **) &h_Ap, bytes )) ;
        HANDLE_ERROR(cudaMallocHost( (float **) &h_Bp, bytes )) ;
        HANDLE_ERROR(cudaMallocHost( (float **) &h_dCp, bytes )) ;
	
	// init matrices with random data
	initData(h_Ap,nx,ny,1); 
	initData(h_Bp,nx,ny,0);

	double timeStampA = getTimeStamp() ;

	//transfer data to dev
	HANDLE_ERROR (cudaMemcpy( d_A, h_Ap, bytes, cudaMemcpyHostToDevice )) ;
	HANDLE_ERROR (cudaMemcpy( d_B, h_Bp, bytes, cudaMemcpyHostToDevice )) ;
		
	double timeStampB = getTimeStamp() ;
	
	// invoke Kernel
	dim3 block( 1024, 1) ; // you will want to configure this
	dim3 grid( (nx+block.x-1)/block.x, (ny+block.y-1)/block.y) ; 
	
	//printf("reached add %d %d %d %d %lu %d %d \n",(nx+block.x-1)/block.x, (ny+block.y-1)/block.y, nx, ny, sizeof(float), noElems, bytes);
	f_addmat<<<grid, block>>>( d_A, d_B, d_C, nx, ny ) ;
	cudaError_t err = cudaGetLastError();
	if (err != cudaSuccess) 
		printf("Error: %s\n", cudaGetErrorString(err));	

	HANDLE_ERROR(cudaDeviceSynchronize()) ;
	
	double timeStampC = getTimeStamp() ;
	
	//copy data back
	HANDLE_ERROR(cudaMemcpy(h_dCp, d_C, bytes, cudaMemcpyDeviceToHost));
	
	double timeStampD = getTimeStamp() ;
	
	// free GPU resources
	cudaFree( d_A ) ; cudaFree( d_B ) ; cudaFree( d_C ) ;
	
	// CPU Matrix add
	h_addmat( h_Ap, h_Bp, h_hC, nx, ny ) ;
	
	// Check results
	int flag = 0;
	for(int i=0;i<(nx);i++){
		for(int j=0;j<(ny);j++){
			if(h_hC[i*(ny)+j] != h_dCp[i*(ny)+j])	
				flag++;
		}
	}
	
	if (flag == 0){
		printf("%.6f %.6f %.6f %.6f\n",(timeStampD-timeStampA),(timeStampB-timeStampA),(timeStampC-timeStampB),(timeStampD-timeStampC));
	}
	else printf("host result is not the same as the device result!");
	
	//free other resourses
	cudaFreeHost(h_Ap); cudaFreeHost(h_Bp);	cudaFreeHost(h_dCp);
        free(h_hC);
	cudaDeviceReset() ;
	
}

