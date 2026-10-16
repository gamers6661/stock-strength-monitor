/* Run the formatter stored with the requested immutable generation. */
const vm=require('vm');
let input='';process.stdin.setEncoding('utf8');
process.stdin.on('data',chunk=>input+=chunk);
process.stdin.on('end',()=>{
  const request=JSON.parse(input),context={};
  vm.createContext(context);
  vm.runInContext(request.formatter,context,{timeout:5000});
  process.stdout.write(context.buildStockCSV(request.rows,request.data,request.contexts));
});
